"""
운세 데이터베이스 모듈 (동기, JSON 파일 기반)
DB 파일: data/fortune_db.json

구조:
{
  "<guild_id>": {
    "config": {
      "channel_id": null,
      "role_id": null,
      "send_time": [],
      "last_ping_date": {}
    },
    "targets": {
      "<user_id>": { "count": 0, "last_used_date": null }
    },
    "buttons": {
      "<message_id>": { "expiration_days": 1, "clicks": [] }
    }
  }
}
"""

import json
from pathlib import Path
from threading import Lock

DB_PATH = Path("data/fortune_db.json")
_lock = Lock()


# ── 내부 헬퍼 ────────────────────────────────────────────

def _load() -> dict:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: dict):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _guild(data: dict, guild_id) -> dict:
    key = str(guild_id)
    if key not in data:
        data[key] = {"config": {}, "targets": {}, "buttons": {}}
    # 누락된 키 보완
    g = data[key]
    g.setdefault("config", {})
    g.setdefault("targets", {})
    g.setdefault("buttons", {})
    return g


# ── 길드 설정 ────────────────────────────────────────────

def get_guild_config(guild_id) -> dict:
    with _lock:
        data = _load()
        return dict(_guild(data, guild_id).get("config", {}))


def set_role_id(guild_id, role_id):
    with _lock:
        data = _load()
        _guild(data, guild_id)["config"]["role_id"] = role_id
        _save(data)


def set_channel_id(guild_id, channel_id):
    with _lock:
        data = _load()
        _guild(data, guild_id)["config"]["channel_id"] = channel_id
        _save(data)


def get_send_times(guild_id) -> list[str]:
    return get_guild_config(guild_id).get("send_time", [])


def add_send_time(guild_id, time_str: str) -> bool:
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        times: list = g["config"].setdefault("send_time", [])
        if time_str in times:
            return False
        times.append(time_str)
        _save(data)
        return True


def remove_send_time(guild_id, time_str: str) -> bool:
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        times: list = g["config"].get("send_time", [])
        if time_str not in times:
            return False
        times.remove(time_str)
        g["config"]["send_time"] = times
        _save(data)
        return True


def set_last_ping_date(guild_id, send_time: str, date_str):
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        g["config"].setdefault("last_ping_date", {})[send_time] = date_str
        _save(data)


# ── 운세 대상 ────────────────────────────────────────────

def get_target(guild_id, user_id) -> dict | None:
    with _lock:
        data = _load()
        return _guild(data, guild_id)["targets"].get(str(user_id))


def list_targets(guild_id) -> list[dict]:
    with _lock:
        data = _load()
        targets = _guild(data, guild_id)["targets"]
        return [{"user_id": uid, **info} for uid, info in targets.items()]


def upsert_target(guild_id, user_id, count: int):
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        uid = str(user_id)
        if uid not in g["targets"]:
            g["targets"][uid] = {"count": count, "last_used_date": None}
        else:
            g["targets"][uid]["count"] = count
        _save(data)


def remove_target(guild_id, user_id) -> bool:
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        uid = str(user_id)
        if uid in g["targets"]:
            del g["targets"][uid]
            _save(data)
            return True
        return False


def mark_target_used(guild_id, user_id, date_str: str):
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        uid = str(user_id)
        if uid in g["targets"]:
            g["targets"][uid]["last_used_date"] = date_str
        _save(data)


def decrement_all_targets() -> dict:
    """자정마다 모든 대상의 count를 1 차감. 0이 된 대상은 삭제."""
    with _lock:
        data = _load()
        updated: list[str] = []
        removed: list[str] = []

        for guild_data in data.values():
            targets: dict = guild_data.get("targets", {})
            to_remove = []
            for uid, info in targets.items():
                count = int(info.get("count", 0))
                if count > 1:
                    info["count"] = count - 1
                    updated.append(uid)
                else:
                    to_remove.append(uid)
            for uid in to_remove:
                del targets[uid]
                removed.append(uid)

        _save(data)
        return {"updated": updated, "removed": removed}


def reset_last_used(guild_id, user_id=None) -> int:
    """일일 사용 제한 초기화. user_id=None이면 길드 전체."""
    with _lock:
        data = _load()
        targets = _guild(data, guild_id)["targets"]
        count = 0

        if user_id is not None:
            uid = str(user_id)
            if uid in targets and targets[uid].get("last_used_date"):
                targets[uid]["last_used_date"] = None
                count = 1
        else:
            for info in targets.values():
                if info.get("last_used_date"):
                    info["last_used_date"] = None
                    count += 1

        if count > 0:
            _save(data)
        return count


# ── 운세 버튼 ────────────────────────────────────────────

def get_button_info(guild_id, message_id) -> dict | None:
    with _lock:
        data = _load()
        return _guild(data, guild_id)["buttons"].get(str(message_id))


def is_button_clicked(guild_id, message_id, user_id) -> bool:
    with _lock:
        data = _load()
        btn = _guild(data, guild_id)["buttons"].get(str(message_id))
        if not btn:
            return False
        return str(user_id) in btn.get("clicks", [])


def record_button_click(guild_id, message_id, user_id):
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        mid = str(message_id)
        if mid not in g["buttons"]:
            return
        clicks: list = g["buttons"][mid].setdefault("clicks", [])
        uid = str(user_id)
        if uid not in clicks:
            clicks.append(uid)
        _save(data)


def create_fortune_button(guild_id, message_id, days: int):
    with _lock:
        data = _load()
        g = _guild(data, guild_id)
        g["buttons"][str(message_id)] = {"expiration_days": days, "clicks": []}
        _save(data)
