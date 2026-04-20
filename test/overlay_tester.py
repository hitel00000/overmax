import cv2
import tkinter as tk
from tkinter import filedialog, simpledialog
import sys
import time
import ctypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from capture.roi_manager import ROIManager
from detection.image_db import ImageDB
from settings import SETTINGS

ctypes.windll.user32.ShowCursor.argtypes = [ctypes.c_bool]

JACKET_SAVE_DIR = Path(__file__).parent / "jackets"


class BorderlessTester:
    def __init__(self):
        self.win_name = "DJMAX RESPECT V"

        self.root = tk.Tk()
        self.root.withdraw()
        self.video_path = filedialog.askopenfilename(
            title="테스트할 게임 영상 선택",
            filetypes=[("Video files", "*.mp4 *.avi *.mkv *.mov")]
        )
        if not self.video_path:
            sys.exit()

        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            sys.exit()

        self.width  = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps    = self.cap.get(cv2.CAP_PROP_FPS) or 30

        self.is_paused = False
        self.cursor_visible = True
        self.last_mouse_move_time = time.time()
        self.current_frame = None
        self.show_roi = False

        self.roiman = ROIManager(self.width, self.height)
        JACKET_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        self.image_db = self._load_image_db()

        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        cv2.resizeWindow(self.win_name, self.width, self.height)
        cv2.setMouseCallback(self.win_name, self.mouse_callback)

        print(f"[Tester] 영상: {self.video_path}")
        print(f"[Tester] 해상도: {self.width}x{self.height}")
        print(f"[Tester] 재킷 저장 경로: {JACKET_SAVE_DIR}")
        print(f"[Tester] 단축키: Space=일시정지  C=재킷캡쳐  R=ROI표시토글  ←/→=5초 이동  ESC=종료")

        self.run()

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            self.last_mouse_move_time = time.time()
            if not self.cursor_visible:
                ctypes.windll.user32.ShowCursor(True)
                self.cursor_visible = True

    def _load_image_db(self) -> ImageDB:
        cfg = SETTINGS["jacket_matcher"]
        db = ImageDB(
            db_path=str(cfg["db_path"]),
            similarity_threshold=float(cfg["similarity_threshold"]),
        )
        if db.initialize():
            db.load()
            print(f"[Tester] ImageDB 로드 완료: {db.song_count}곡")
        else:
            print("[Tester] ImageDB 로드 실패 - song_id 자동완성 비활성")
        return db

    def _search_song_id(self, jacket: cv2.Mat) -> tuple[str, float] | None:
        """재킷 이미지로 ImageDB 검색. 결과 없으면 None."""
        if not self.image_db.is_ready or self.image_db.song_count == 0:
            return None
        result = self.image_db.search(jacket)
        return result  # (song_id, score) | None

    def _capture_jacket(self, frame):
        """현재 프레임에서 재킷 ROI를 크롭하고 song_id 입력 후 저장."""
        x1, y1, x2, y2 = self.roiman.get_roi("jacket")
        jacket = frame[y1:y2, x1:x2]

        if jacket.size == 0:
            print("[Tester] 재킷 ROI가 비어있음")
            return

        # ImageDB 검색 → 기본값 준비
        search_result = self._search_song_id(jacket)
        if search_result:
            default_id, score = search_result
            hint = f"DB 매칭: {default_id}  (유사도 {score:.3f})"
        else:
            default_id, hint = "", "DB 매칭 없음"
        print(f"[Tester] {hint}")

        # 미리보기
        preview = cv2.resize(jacket, (240, 240), interpolation=cv2.INTER_NEAREST)
        cv2.imshow("재킷 미리보기 (아무 키나 누르면 닫힘)", preview)
        cv2.waitKey(1)

        # song_id 입력 (기본값 주입)
        song_id = simpledialog.askstring(
            "song_id 입력",
            f"이 재킷의 song_id (숫자)를 입력하세요.\n비워두면 저장하지 않습니다.\n{hint}",
            initialvalue=default_id,
            parent=self.root,
        )
        cv2.destroyWindow("재킷 미리보기 (아무 키나 누르면 닫힘)")

        if not song_id or not song_id.strip().isdigit():
            print("[Tester] 저장 취소 (입력 없음 또는 숫자 아님)")
            return

        song_id = song_id.strip()
        save_path = JACKET_SAVE_DIR / f"{song_id}.png"

        # 이미 있으면 확인
        if save_path.exists():
            overwrite = simpledialog.askstring(
                "덮어쓰기 확인",
                f"{song_id}.png 이미 존재합니다. 덮어쓸까요? (y/N)",
                parent=self.root,
            )
            if not overwrite or overwrite.strip().lower() != "y":
                print(f"[Tester] 저장 취소: {save_path}")
                return

        cv2.imwrite(str(save_path), jacket)
        print(f"[Tester] 저장 완료: {save_path}  (크기: {jacket.shape[1]}x{jacket.shape[0]})")

    def run(self):
        while True:
            if not self.is_paused:
                ret, frame = self.cap.read()
                if not ret:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                self.current_frame = frame

                if self.cursor_visible and (time.time() - self.last_mouse_move_time > 2.0):
                    ctypes.windll.user32.ShowCursor(False)
                    self.cursor_visible = False

            # ROI 경계 표시 (show_roi 플래그 기준)
            display = self.current_frame.copy() if self.current_frame is not None else None
            if display is not None:
                if self.show_roi:
                    x1, y1, x2, y2 = self.roiman.get_roi("jacket")
                    cv2.rectangle(display, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(
                        display, "JACKET ROI",
                        (x1, max(12, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1,
                    )
                cv2.imshow(self.win_name, display)

            key = cv2.waitKeyEx(int(1000 / self.fps))

            if key == 27:    # ESC
                break
            elif key == ord(' '):
                self.is_paused = not self.is_paused
            elif key == ord('c') or key == ord('C'):
                if self.current_frame is not None:
                    self._capture_jacket(self.current_frame)
                else:
                    print("[Tester] 캡처할 프레임 없음")
            elif key == ord('r') or key == ord('R'):
                self.show_roi = not self.show_roi
                print(f"[Tester] ROI 표시: {'ON' if self.show_roi else 'OFF'}")
            elif key == 2424832:  # Left
                pos = self.cap.get(cv2.CAP_PROP_POS_MSEC)
                self.cap.set(cv2.CAP_PROP_POS_MSEC, max(0, pos - 5000))
            elif key == 2555904:  # Right
                pos = self.cap.get(cv2.CAP_PROP_POS_MSEC)
                self.cap.set(cv2.CAP_PROP_POS_MSEC, pos + 5000)

            if cv2.getWindowProperty(self.win_name, cv2.WND_PROP_VISIBLE) < 1:
                break

        if not self.cursor_visible:
            ctypes.windll.user32.ShowCursor(True)
        self.cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    BorderlessTester()
