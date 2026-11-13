"""Print the unique release name and numeric Windows file version.

Called once by build_installer.bat; both editions share that build identity.
This tool reads no account, configuration or report files.
"""
from datetime import datetime
from uuid import uuid4


def versions(now=None):
    now = now or datetime.now()
    release = f"{now:%Y.%m.%d.%H%M%S}-{uuid4().hex}"
    # Windows file versions have four numeric components, each <= 65535.
    # The unique release name belongs in AppVersion and the Setup filename.
    windows = f"{now.year}.{now.month}.{now.day}.{now.hour * 60 + now.minute}"
    return release, windows


if __name__ == "__main__":
    print(*versions())
