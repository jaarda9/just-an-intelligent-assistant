"""Camera feed and video player — the things that take over the HUD's centre.

Mixed into ui.window.MainWindow; methods use its widgets via self."""
from __future__ import annotations

import threading
import time
from PyQt6.QtCore import QSizeF, QUrl, Qt
from PyQt6.QtGui import QPixmap
from pathlib import Path
from .base import CONFIG_DIR, HAVE_VIDEO, QMediaPlayer, _OS, _RIGHT_W
from .widgets import _CameraPreview

class MediaMixin:
    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    # ── HUD browser ──────────────────────────────────────────────────────────
    def _restore_centre(self) -> None:
        """What the centre shows when a camera / video takes its leave: the
        browser if it still has tabs open, otherwise the HUD."""
        if getattr(self, "_browser_open", False) and self._browser.has_tabs():
            self._hud_cam_stack.setCurrentIndex(3)
        else:
            self._hud_cam_stack.setCurrentIndex(0)

    def _show_browser(self) -> None:
        self._browser_open = True
        self._hud_cam_stack.setCurrentIndex(3)

    def _close_browser(self) -> None:
        """Back to the HUD. Tabs stay alive, so reopening is instant."""
        self._browser_open = False
        self._hud_cam_stack.setCurrentIndex(0)

    def _on_browser_cmd(self, cmd: str, payload) -> None:
        """Runs on the Qt thread. payload is a dict; if it carries 'reply'
        (a list) and 'done' (a threading.Event) the result is handed back."""
        p = payload or {}
        b = self._browser
        out = ""
        try:
            if cmd == "open":
                i = b.open(p.get("target", ""), new_tab=p.get("new_tab", True))
                self._show_browser()
                out = f"Opened in tab {i + 1}."
            elif cmd == "show":
                if not b.has_tabs():
                    b.new_tab()
                self._show_browser()
                out = "Browser shown."
            elif cmd == "hide":
                self._close_browser()
                out = "Back to the HUD."
            elif cmd == "close":
                idx = p.get("index")
                b.close_tab(None if idx is None else int(idx))
                out = "Tab closed."
            elif cmd == "switch":
                ok = b.switch(int(p.get("index", -1)))
                if ok:
                    self._show_browser()
                out = "Switched." if ok else "No such tab."
            elif cmd in ("back", "forward", "reload"):
                b._call(cmd)
                out = f"Done: {cmd}."
            elif cmd == "list":
                out = b.tabs()
            elif cmd == "read":
                def got(title, url, text):
                    p["reply"].append((title, url, text))
                    p["done"].set()
                b.read_current(got)
                return                                    # replied asynchronously
        except Exception as e:
            out = f"Browser error: {e}"
        if "reply" in p:
            p["reply"].append(out)
            p["done"].set()

    def _on_cam_stream(self, start: bool) -> None:
        if start:
            self._hud_cam_stack.setCurrentIndex(1)
        else:
            self._restore_centre()
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def start_camera_stream(self) -> None:
        # Already streaming: just make sure the feed is what is on screen. A
        # second capture thread could not open the camera the first one holds,
        # and its exit would switch the centre back to the HUD.
        t = getattr(self, "_cam_thread", None)
        if t is not None and t.is_alive() and not self._cam_stop.is_set():
            self._cam_stream_sig.emit(True)
            return
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        self._cam_thread = t
        t.start()

    def camera_snapshot(self, max_age: float = 1.0):
        """The live feed's latest frame (JPEG bytes) if the camera is streaming,
        else None. Lets a question about the camera use the open stream instead
        of reopening a device it already holds. Safe from any thread."""
        t = getattr(self, "_cam_thread", None)
        last = getattr(self, "_cam_last", None)
        if t is None or not t.is_alive() or last is None:
            return None
        data, at = last
        return data if time.monotonic() - at <= max_age else None

    def _cam_loop(self) -> None:
        from core import camera
        cap = None
        try:
            import cv2
            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j
                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                cap = camera.open_camera(cam_idx)
            except camera.CameraError as e:
                # Say so — the feed used to just close with no explanation.
                print(f"[Camera] {e}")
                self._log.append_log(f"ERR: Camera — {e}")
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            fails = 0
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    fails = 0
                    camera.publish(frame)                   # for snapshots / presence
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    data = buf.tobytes()
                    self._cam_last = (data, time.monotonic())   # for camera_snapshot()
                    self._cam_frame_sig.emit(data)
                else:
                    fails += 1
                    if fails == 60:                         # ~2 s with no picture
                        print("[Camera] no frames from the camera")
                        self._log.append_log("ERR: Camera — opened, but sends no picture "
                                             "(in use by another app, or the wrong camera "
                                             "index in config/api_keys.json).")
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            if cap is not None:
                cap.release()
            camera.clear()
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # --- Video in the HUD area ---------------------------------------------
    #
    # Everything below runs on the Qt thread. Plugins and the assistant reach it
    # through the signals above, the same way every other panel is driven, so a
    # background thread never touches a widget.
    def _on_video_open(self, source: str, title: str, muted: bool,
                       audio_source: str = "") -> None:
        if not HAVE_VIDEO or not self._video_player:
            self.write_log("SYS: Video playback is not available in this Qt "
                           "install.")
            return
        # A video and the live camera cannot share the centre of the HUD.
        self._cam_stop.set()

        self._video_title.setText(f"▶  {(title or 'VIDEO')[:44].upper()}")
        self._video_split = bool(audio_source)
        self._set_video_muted(bool(muted))

        url = (QUrl.fromLocalFile(source) if Path(source).exists()
               else QUrl(source))
        self._video_player.setSource(url)
        if self._video_split:
            self._video_sound.setSource(QUrl(audio_source))
        self._hud_cam_stack.setCurrentIndex(2)
        self._video_on = True
        # Re-run now that the video counts as playing: _set_video_muted ran
        # before this line and saw no video, so its mic check was a no-op.
        self._sync_mic_for_video()
        self._video_player.play()
        if self._video_split:
            self._video_sound.play()
            self._video_sync.start()

    def _fit_video(self, *_a) -> None:
        """Size the picture to the panel, keeping its shape."""
        if not (self._video_item and self._video_widget):
            return
        try:
            native = self._video_item.nativeSize()
            if native.isEmpty():
                return
            view = self._video_widget.viewport().size()
            scale = min(view.width() / native.width(),
                        view.height() / native.height())
            w, h = native.width() * scale, native.height() * scale
            self._video_item.setSize(QSizeF(w, h))
            self._video_scene.setSceneRect(0, 0, w, h)
            self._video_widget.centerOn(self._video_item)
        except Exception:
            pass

    def _on_video_close(self) -> None:
        if self._video_sync:
            self._video_sync.stop()
        for p in (self._video_player, self._video_sound):
            if p:
                p.stop()
                p.setSource(QUrl())
        self._video_split = False
        self._video_on = False
        self._restore_centre()          # back to the browser if it was open, else the HUD
        self._sync_mic_for_video()      # gives the microphone back

    def _set_video_muted(self, muted: bool) -> None:
        """Silence whichever output is carrying the sound for this video."""
        muted = bool(muted)
        if self._video_audio:
            # When the sound is a separate stream this player has none, but
            # muting it too costs nothing and keeps the two paths identical.
            self._video_audio.setMuted(muted)
        if self._video_sound_out:
            self._video_sound_out.setMuted(muted)
        self._sync_video_mute_btn()
        self._sync_mic_for_video()

    def _on_video_mute(self, muted: bool) -> None:
        self._set_video_muted(muted)

    def _sync_mic_for_video(self) -> None:
        """Close the microphone while the video is making sound.

        JARVIS subtracts its OWN output from the microphone — that is what
        core/echo.py does — but a video plays through a different output
        entirely, so the guard has never heard of it and the assistant answers
        the film. There is no arrangement in which an open microphone and a
        loudspeaker in the same room do not do that.

        So the microphone closes for exactly as long as the sound is on, and
        opens again by itself the moment it goes off or the video is closed.
        Only if JARVIS closed it: a microphone the user muted themselves stays
        muted, and pressing the mute key during a video hands the decision back
        to them for good.
        """
        out = self._video_sound_out if self._video_split else self._video_audio
        sound_on = bool(self._video_on and out and not out.isMuted())

        # Better than closing the microphone: listen for his NAME only. The
        # soundtrack is never sent to the model (so it cannot answer the film),
        # but "Jarvis …" ducks the video and opens the microphone for the
        # command. Available when interrupt-by-name is on and its model loaded.
        gate_ok = False
        try:
            gate_ok = bool(self.video_name_gate and self.video_name_gate())
        except Exception:
            gate_ok = False
        if gate_ok:
            if self._video_auto_muted:              # switching from the old way
                self._video_auto_muted = False
                self._set_muted(False)
            if sound_on and not self._video_gate:
                self._log.append_log("SYS: Video sound on — say “Jarvis” to talk to me.")
            if not sound_on:
                self._duck_video(False)
            self._video_gate = sound_on
            return
        self._video_gate = False

        if sound_on and not self._muted:
            self._video_auto_muted = True
            self._set_muted(True, "The video's sound is on — silence it, close "
                                  "it, or press F4 to talk. Typing still works.")
        elif not sound_on and self._video_auto_muted:
            self._video_auto_muted = False
            self._set_muted(False, "The video is quiet again.")

    def _duck_video(self, on: bool) -> None:
        """Turn the video down while the user talks to JARVIS (Qt thread)."""
        for o in (self._video_audio, self._video_sound_out):
            if o is not None:
                try:
                    o.setVolume(0.12 if on else 1.0)
                except Exception:
                    pass
        self._video_ducked = bool(on)

    def _sync_video_sound(self) -> None:
        """Keep the separate soundtrack in step with the picture.

        Two players started at the same moment do not stay together: they buffer
        independently, and measured on a real stream they were about half a
        second apart after nine seconds. So the sound is nudged back to the
        picture whenever it drifts far enough to hear — and only then, because
        correcting a smaller gap is itself audible.
        """
        if not (self._video_split and self._video_sound and self._video_player):
            return
        try:
            if self._video_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                return
            drift = self._video_sound.position() - self._video_player.position()
            if abs(drift) > 300:
                self._video_sound.setPosition(self._video_player.position())
        except Exception:
            pass

    def _sync_video_mute_btn(self) -> None:
        out = self._video_sound_out if self._video_split else self._video_audio
        muted = bool(out and out.isMuted())
        self._video_mute_btn.setText("🔇  SOUND OFF" if muted else "🔊  SOUND ON")

    def _toggle_video_mute(self) -> None:
        out = self._video_sound_out if self._video_split else self._video_audio
        if out:
            self._set_video_muted(not out.isMuted())

    def _on_video_error(self, *_a) -> None:
        err = ""
        try:
            err = self._video_player.errorString()
        except Exception:
            pass
        self.write_log(f"SYS: The video could not be played{(' — ' + err) if err else ''}.")
        self._on_video_close()

    def stop_video(self) -> None:
        self._video_close_sig.emit()

    def video_is_playing(self) -> bool:
        return bool(self._video_on)
