"""
Overmax - DJMAX Respect V 비공식 난이도 오버레이
메인 진입점 — 모든 컴포넌트를 조립하고 실행
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.app import OvermaxApp
from core.utils import show_error_message

def main():
    try:
        app = OvermaxApp()
        app.run()
    except KeyboardInterrupt:
        print("\n[Main] 종료 중...")
    except Exception as e:
        msg = f"프로그램 실행 중 예기치 못한 에러가 발생했습니다:\n\n{e}"
        print(f"[Main] {msg}")
        show_error_message(msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
