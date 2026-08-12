"""适配器注册与匹配自检（UTF-8 安全）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sites import get_adapter, list_adapters  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("已注册:", list_adapters())
    for name in [
        "中海油采办业务管理与交易系统",
        "中国华能集团电子商务平台",
        "中国石油招标投标网",
        "中国石化电子招投标平台",
        "山东能源集团招标投标交易平台",
        "上海政府采购网",
        "浙江政府采购网",
    ]:
        a = get_adapter(name)
        print(f"  {name} -> {a.__name__ if a else '未匹配'}")


if __name__ == "__main__":
    main()
