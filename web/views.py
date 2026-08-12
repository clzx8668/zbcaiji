"""
API 蓝图 — 任务管控 + 数据查询。
"""
import threading
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request, current_app
from loguru import logger

task_bp = Blueprint("task", __name__)
data_bp = Blueprint("data", __name__)

# 系统时区：Asia/Shanghai (UTC+8)
TZ_SHANGHAI = timezone(timedelta(hours=8))


def _fmt_time(dt, fmt="%Y-%m-%d %H:%M"):
    """将 UTC 时间转换为系统时区（Asia/Shanghai）并格式化"""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_SHANGHAI).strftime(fmt)


def _get_manager():
    """获取注入到 app 的 TaskManager 实例"""
    return current_app.extensions.get("task_manager")


@task_bp.route("/status")
def task_status():
    """GET /api/task/status — 获取调度器状态"""
    manager = _get_manager()
    if not manager:
        return jsonify({"running": False, "jobs": [], "job_count": 0, "error": "TaskManager 未初始化"})

    # 每次请求都重新加载站点配置（确保数据最新）
    manager.load_configs()
    status = manager.get_status()

    status["sites"] = [
        {
            "name": c.site_name,
            "url": c.site_url,
            "keywords": c.keywords_str,
            "cron_expr": c.cron_expr,
            "days_back": c.days_back,
        }
        for c in manager._configs
    ]

    return jsonify(status)


@task_bp.route("/start", methods=["POST"])
def task_start():
    """POST /api/task/start — 启动调度器"""
    manager = _get_manager()
    if not manager:
        return jsonify({"success": False, "message": "TaskManager 未初始化"}), 500

    result = manager.start()
    return jsonify(result)


@task_bp.route("/stop", methods=["POST"])
def task_stop():
    """POST /api/task/stop — 停止调度器"""
    manager = _get_manager()
    if not manager:
        return jsonify({"success": False, "message": "TaskManager 未初始化"}), 500

    result = manager.stop()
    return jsonify(result)


@task_bp.route("/run/<site_name>", methods=["POST"])
def task_run(site_name):
    """POST /api/task/run/<site_name> — 立即执行指定站点爬取"""
    manager = _get_manager()
    if not manager:
        return jsonify({"success": False, "message": "TaskManager 未初始化"}), 500

    # 在后台线程执行以避免阻塞响应
    def _run():
        manager.run_once(site_name)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"success": True, "message": f"正在执行: {site_name}"})


@task_bp.route("/backup", methods=["POST"])
def task_backup():
    """POST /api/task/backup — 手动备份数据库"""
    from web.backup import backup_database
    path = backup_database()
    if path:
        return jsonify({"success": True, "message": f"备份完成: {path}", "path": path})
    return jsonify({"success": False, "message": "备份失败"}), 500


# ── 站点配置 CRUD API ──

@task_bp.route("/sites", methods=["GET"])
def site_list():
    """GET /api/task/sites — 获取所有站点配置"""
    from utils.site_config_manager import SiteConfigManager
    mgr = SiteConfigManager()
    all_sites = mgr.get_all(enabled_only=False)
    return jsonify({
        "sites": [SiteConfigManager.config_to_dict(c) for c in all_sites],
        "count": len(all_sites),
    })


# ── 归档/批量操作 API ──

@data_bp.route("/items/<int:item_id>/archive", methods=["POST"])
def archive_item(item_id):
    """POST /api/data/items/<id>/archive — 归档单条记录"""
    from web.models import db, CrawlItem

    item = CrawlItem.query.get(item_id)
    if not item:
        return jsonify({"success": False, "message": "记录不存在"}), 404

    item.archived = 1
    item.archived_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "message": "已归档"})


@data_bp.route("/items/<int:item_id>/unarchive", methods=["POST"])
def unarchive_item(item_id):
    """POST /api/data/items/<id>/unarchive — 取消归档"""
    from web.models import db, CrawlItem

    item = CrawlItem.query.get(item_id)
    if not item:
        return jsonify({"success": False, "message": "记录不存在"}), 404

    item.archived = 0
    item.archived_at = None
    db.session.commit()
    return jsonify({"success": True, "message": "已取消归档"})


@data_bp.route("/items/batch/archive", methods=["POST"])
def batch_archive():
    """POST /api/data/items/batch/archive — 批量归档，body: {"ids": [1,2,3]}"""
    from web.models import db, CrawlItem

    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"success": False, "message": "未提供记录 ID"}), 400

    now = datetime.utcnow()
    updated = CrawlItem.query.filter(
        CrawlItem.id.in_(ids), CrawlItem.archived == 0
    ).update({"archived": 1, "archived_at": now}, synchronize_session=False)
    db.session.commit()

    return jsonify({"success": True, "message": f"已归档 {updated} 条记录"})


@data_bp.route("/items/batch/unarchive", methods=["POST"])
def batch_unarchive():
    """POST /api/data/items/batch/unarchive — 批量取消归档"""
    from web.models import db, CrawlItem

    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"success": False, "message": "未提供记录 ID"}), 400

    updated = CrawlItem.query.filter(
        CrawlItem.id.in_(ids), CrawlItem.archived == 1
    ).update({"archived": 0, "archived_at": None}, synchronize_session=False)
    db.session.commit()

    return jsonify({"success": True, "message": f"已取消归档 {updated} 条记录"})


@data_bp.route("/items/batch/delete", methods=["POST"])
def batch_delete():
    """POST /api/data/items/batch/delete — 批量删除（仅已归档记录）"""
    from web.models import db, CrawlItem

    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"success": False, "message": "未提供记录 ID"}), 400

    deleted = CrawlItem.query.filter(
        CrawlItem.id.in_(ids), CrawlItem.archived == 1
    ).delete(synchronize_session=False)
    db.session.commit()

    return jsonify({"success": True, "message": f"已删除 {deleted} 条记录"})


@task_bp.route("/sites", methods=["POST"])
def site_create():
    """POST /api/task/sites — 新增站点配置"""
    data = request.get_json(force=True, silent=True) or {}
    site_name = data.get("site_name", "").strip()
    if not site_name:
        return jsonify({"success": False, "message": "站点名称不能为空"}), 400
    if not data.get("site_url", "").strip():
        return jsonify({"success": False, "message": "站点地址不能为空"}), 400

    from utils.site_config_manager import SiteConfigManager
    mgr = SiteConfigManager()
    ok = mgr.save(
        site_name=site_name,
        site_url=data.get("site_url", "").strip(),
        search_type=data.get("search_type", "both"),
        keywords=data.get("keywords", ""),
        days_back=int(data.get("days_back", 7)),
        search_url=data.get("search_url", ""),
        cron_expr=data.get("cron_expr", "0 9 * * *"),
        enabled=data.get("enabled", True),
        proxy=data.get("proxy", ""),
        notes=data.get("notes", ""),
    )
    if ok:
        # 通知 TaskManager 重新加载配置
        manager = _get_manager()
        if manager:
            manager.reload_configs()
        return jsonify({"success": True, "message": f"已添加站点: {site_name}"})
    return jsonify({"success": False, "message": "保存失败"}), 500


@task_bp.route("/sites/<site_name>", methods=["PUT"])
def site_update(site_name):
    """PUT /api/task/sites/<site_name> — 更新站点配置"""
    data = request.get_json(force=True, silent=True) or {}
    from utils.site_config_manager import SiteConfigManager
    mgr = SiteConfigManager()

    existing = mgr.get_by_name(site_name)
    if not existing:
        return jsonify({"success": False, "message": f"站点不存在: {site_name}"}), 404

    ok = mgr.save(
        site_name=site_name,
        site_url=data.get("site_url", existing.site_url),
        search_type=data.get("search_type", existing.search_type),
        keywords=data.get("keywords", existing.keywords_str),
        days_back=int(data.get("days_back", existing.days_back)),
        search_url=data.get("search_url", existing.search_url),
        cron_expr=data.get("cron_expr", existing.cron_expr),
        enabled=data.get("enabled", existing.enabled),
        proxy=data.get("proxy", existing.proxy or ""),
        notes=data.get("notes", existing.notes),
    )
    if ok:
        # 通知 TaskManager 重新加载配置
        manager = _get_manager()
        if manager:
            manager.reload_configs()
        return jsonify({"success": True, "message": f"已更新: {site_name}"})
    return jsonify({"success": False, "message": "更新失败"}), 500


@task_bp.route("/sites/<site_name>", methods=["DELETE"])
def site_delete(site_name):
    """DELETE /api/task/sites/<site_name> — 删除站点配置"""
    from utils.site_config_manager import SiteConfigManager
    mgr = SiteConfigManager()
    if not mgr.exists(site_name):
        return jsonify({"success": False, "message": f"站点不存在: {site_name}"}), 404

    mgr.delete(site_name)
    # 通知 TaskManager 重新加载配置
    manager = _get_manager()
    if manager:
        manager.reload_configs()
    return jsonify({"success": True, "message": f"已删除: {site_name}"})


# ── 数据查询 API ──

@data_bp.route("/stats")
def data_stats():
    """GET /api/data/stats — Dashboard 统计数据"""
    from web.models import db, CrawlItem, CrawlTask

    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_items = CrawlItem.query.filter(CrawlItem.archived == 0).count()
    week_new = CrawlItem.query.filter(CrawlItem.archived == 0, CrawlItem.first_seen >= week_ago).count()
    today_new = CrawlItem.query.filter(CrawlItem.archived == 0, CrawlItem.first_seen >= today_start).count()
    total_tasks = CrawlTask.query.count()
    recent_tasks = CrawlTask.query.filter(CrawlTask.run_at >= week_ago).count()
    active_sites = CrawlItem.query.with_entities(CrawlItem.site_name).filter(CrawlItem.archived == 0).distinct().count()

    # 最近任务状态
    recent_runs = CrawlTask.query.order_by(CrawlTask.run_at.desc()).limit(5).all()
    recent = [{"site_name": t.site_name, "status": t.status, "run_at": _fmt_time(t.run_at, "%m-%d %H:%M") or "-",
               "items_new": t.items_new, "error_msg": (t.error_msg[:60] if t.error_msg else None)}
              for t in recent_runs]

    return jsonify({
        "total_items": total_items,
        "week_new": week_new,
        "today_new": today_new,
        "total_tasks": total_tasks,
        "recent_tasks": recent_tasks,
        "active_sites": active_sites,
        "recent_runs": recent,
    })


@data_bp.route("/items")
def data_items():
    """GET /api/data/items?page=1&per_page=20&site=&keyword=&type= — 分页查询爬取资料"""
    from web.models import CrawlItem

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    site_name = request.args.get("site", "").strip()
    keyword = request.args.get("keyword", "").strip()
    item_type = request.args.get("type", "").strip()
    show_archived = request.args.get("archived", "0")  # "1" = 只看已归档, "0" = 只看未归档, "all" = 全部

    query = CrawlItem.query

    if show_archived == "1":
        query = query.filter(CrawlItem.archived == 1)
    elif show_archived == "0":
        query = query.filter(CrawlItem.archived == 0)
    # "all" = no filter

    if site_name:
        query = query.filter(CrawlItem.site_name == site_name)
    if keyword:
        query = query.filter(
            CrawlItem.title.contains(keyword) | CrawlItem.detail_text.contains(keyword)
        )
    if item_type:
        query = query.filter(CrawlItem.item_type == item_type)

    total = query.count()
    items = query.order_by(CrawlItem.first_seen.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return jsonify({
        "items": [{
            "id": i.id,
            "title": i.title,
            "site_name": i.site_name,
            "url": i.url,
            "publish_date": i.publish_date,
            "item_type": i.item_type,
            "keywords_matched": i.keywords_matched,
            "amount": i.amount,
            "source_org": i.source_org,
            "detail_text": (i.detail_text[:200] if i.detail_text else ""),
            "first_seen": _fmt_time(i.first_seen),
            "archived": i.archived,
            "archived_at": _fmt_time(i.archived_at) or None,
        } for i in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "sites": [r[0] for r in CrawlItem.query.with_entities(CrawlItem.site_name).filter(CrawlItem.archived == (1 if show_archived == "1" else 0)).distinct().order_by(CrawlItem.site_name).all()] if show_archived != "all" else [],
    })


@data_bp.route("/tasks")
def data_tasks():
    """GET /api/data/tasks?page=1&per_page=20 — 任务执行记录"""
    from web.models import CrawlTask

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = CrawlTask.query.order_by(CrawlTask.run_at.desc())
    total = query.count()
    tasks = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        "tasks": [{
            "id": t.id,
            "site_name": t.site_name,
            "run_at": _fmt_time(t.run_at, "%Y-%m-%d %H:%M:%S") or "",
            "status": t.status,
            "items_found": t.items_found,
            "items_new": t.items_new,
            "error_msg": t.error_msg,
        } for t in tasks],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    })


@data_bp.route("/logs")
def data_logs():
    """GET /api/data/logs?file=&keyword=&lines=200 — 读取日志"""
    from web.log_reader import list_log_files, read_log

    file_param = request.args.get("file", "")
    keyword = request.args.get("keyword", "")
    lines_param = request.args.get("lines", 200, type=int)

    max_lines = min(lines_param, 2000)

    log_files = list_log_files()
    content = []
    current_file = file_param

    if file_param:
        content = read_log(file_param, max_lines, keyword=keyword if keyword else "")
    elif log_files:
        current_file = log_files[0]["path"]
        content = read_log(current_file, max_lines)

    return jsonify({
        "files": log_files,
        "current_file": current_file,
        "content": content,
        "keyword": keyword,
    })
