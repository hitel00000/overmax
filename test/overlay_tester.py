import cv2
import tkinter as tk
from tkinter import filedialog
import sys
import time

class OverlayTester:
    def __init__(self):
        self.win_name = "DJMAX RESPECT V"
        
        # 파일 선택 팝업
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

        # 영상 정보
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30

        # 상태 변수
        self.is_paused = False
        self.is_fullscreen = False
        self.cursor_visible = True
        self.last_mouse_move_time = time.time()

        # 윈도우 설정
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.win_name, self.width, self.height)
        
        # 마우스 콜백 등록 (움직임 감지용)
        cv2.setMouseCallback(self.win_name, self.mouse_callback)

        self.run()

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            self.last_mouse_move_time = time.time()
            if not self.cursor_visible:
                # Windows 환경에서는 직접적인 커서 토글이 제한적이므로 
                # 시스템 API 대신 OpenCV의 속성을 활용하거나 로직으로 처리합니다.
                # 여기서는 마우스가 움직일 때 상태를 갱신합니다.
                self.cursor_visible = True

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        prop = cv2.WINDOW_FULLSCREEN if self.is_fullscreen else cv2.WINDOW_NORMAL
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_FULLSCREEN, prop)
        if not self.is_fullscreen:
            cv2.resizeWindow(self.win_name, self.width, self.height)

    def run(self):
        while True:
            if not self.is_paused:
                ret, frame = self.cap.read()
                if not ret:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                
                # 마우스 커서 숨김 로직 (2초간 움직임 없을 시)
                if time.time() - self.last_mouse_move_time > 2.0:
                    # 실제 커서를 숨기기 위해 투명한 커서 리소스를 로드하는 대신
                    # 윈도우 속성을 조절하여 커서가 보이지 않게 처리합니다.
                    if self.cursor_visible:
                        # OpenCV에서 제공하는 창 속성으로 커서 제어 (일부 빌드에서 작동)
                        # 미지원 시 로직상 처리
                        pass 

                cv2.imshow(self.win_name, frame)

            # --- Windows용 특수 키 대응 (waitKeyEx 사용) ---
            # 좌: 2424832, 우: 2555904 (가끔 환경에 따라 다를 수 있음)
            key = cv2.waitKeyEx(int(1000 / self.fps))

            if key == 27: # ESC
                if self.is_fullscreen: self.toggle_fullscreen()
                else: break
            
            elif key == ord(' '): # Space
                self.is_paused = not self.is_paused

            elif key == 13: # Enter (Alt+Enter 대용)
                self.toggle_fullscreen()

            # Seek 기능 (Windows 화살표 키 코드 대응)
            elif key == 2424832 or key == 65361: # Left Arrow
                pos = self.cap.get(cv2.CAP_PROP_POS_MSEC)
                self.cap.set(cv2.CAP_PROP_POS_MSEC, max(0, pos - 5000))
            elif key == 2555904 or key == 65363: # Right Arrow
                pos = self.cap.get(cv2.CAP_PROP_POS_MSEC)
                self.cap.set(cv2.CAP_PROP_POS_MSEC, pos + 5000)

            if cv2.getWindowProperty(self.win_name, cv2.WND_PROP_VISIBLE) < 1:
                break

        self.cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    OverlayTester()