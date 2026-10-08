"""古籍智能校勘系统 —— FastAPI 后端包（薄 BFF，见 TECH_DESIGN §1、§4）。"""

import sys

# 解释器版本闸门放在包初始化里，保证 `uvicorn server.main:app` 一启动就先检查。
# 不这么做的话，若误用系统自带的低版本 Python（本机默认是 3.8），
# 报错会是一句很难懂的 pydantic TypeError: Unable to evaluate type annotation 'list[CollationType]'，
# 让人以为是代码写错了。这里直接说清「该用哪个 Python、怎么用」。
if sys.version_info < (3, 11):
    raise RuntimeError(
        "本项目后端要求 Python >= 3.11（PRD §5 / TECH_DESIGN §4），"
        f"当前解释器是 {sys.version.split()[0]}（{sys.executable}）。\n"
        "请用仓库内的虚拟环境启动：\n"
        "  Windows : .venv/Scripts/activate   然后 npm run dev:server\n"
        "  macOS/Linux: source .venv/bin/activate  然后 npm run dev:server\n"
        "尚未创建虚拟环境时，先执行：\n"
        "  py -3.11 -m venv .venv && .venv/Scripts/pip install -r requirements.txt"
    )
