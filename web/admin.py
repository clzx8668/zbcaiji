"""
Flask-Admin 管理界面配置 — 注册模型视图、自定义 Dashboard。
"""
from flask import request, redirect, url_for
from flask_admin import Admin, AdminIndexView, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from markupsafe import Markup
from web.models import CrawlItem, CrawlTask, ItemChange, SiteConfigModel


# ─── 带认证保护的 AdminIndexView ───

class AuthAdminIndexView(AdminIndexView):
    @expose("/")
    def index(self):
        return self.render("admin/spa.html")


# ─── 受保护的 ModelView 基类 ───

class AuthModelView(ModelView):
    """所有管理视图的基础类，添加认证保护"""

    def is_accessible(self):
        return True  # HTTP Basic Auth 由蓝图层处理

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("admin.index"))


# ─── 爬取资料管理 ───

class CrawlItemAdmin(AuthModelView):
    """items 表管理视图"""
    can_create = False  # 不允许手动创建
    can_export = True
    export_max_rows = 10000
    column_export_list = [
        "id", "title", "site_name", "url", "publish_date",
        "item_type", "keywords_matched", "amount", "source_org",
        "detail_text", "first_seen", "last_updated",
    ]

    column_list = [
        "title", "site_name", "publish_date", "item_type",
        "keywords_matched", "amount", "source_org", "first_seen",
    ]
    column_sortable_list = ["publish_date", "first_seen", "site_name", "item_type"]
    column_searchable_list = ["title", "site_name", "keywords_matched", "detail_text"]
    column_filters = ["site_name", "item_type", "publish_date"]
    column_default_sort = ("first_seen", True)  # 默认按首次入库时间降序

    # 分页
    page_size = 50
    can_view_details = True

    # 列表页 URL 渲染为链接
    column_formatters = {
        "title": lambda v, c, m, p: Markup(
            f'<a href="{m.url}" target="_blank" title="查看原页面">{m.title[:60]}</a>'
            if m.url and m.title else m.title or "-"
        ),
        "detail_text": lambda v, c, m, p: (
            m.detail_text[:50] + "..." if m.detail_text and len(m.detail_text) > 50 else m.detail_text
        ) or "-",
    }

    # 详情页展示完整字段
    column_details_list = [
        "title", "site_name", "url", "publish_date", "item_type",
        "keywords_matched", "amount", "source_org", "detail_text",
        "first_seen", "last_updated", "url_hash",
    ]

    # 表单配置
    form_columns = [
        "title", "site_name", "url", "publish_date", "item_type",
        "keywords_matched", "amount", "source_org", "detail_text",
    ]


# ─── 任务记录管理（只读） ───

class CrawlTaskAdmin(AuthModelView):
    """tasks 表管理视图 — 只读"""
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True

    column_list = [
        "id", "site_name", "run_at", "status",
        "items_found", "items_new", "error_msg",
    ]
    column_sortable_list = ["run_at", "status", "site_name"]
    column_filters = ["status", "site_name"]
    column_default_sort = ("run_at", True)
    page_size = 50

    # 状态颜色标记
    def _status_color(view, context, model, name):
        color = {
            "success": "#28a745",
            "failed": "#dc3545",
            "running": "#007bff",
        }.get(model.status, "#6c757d")
        return Markup(f'<span style="color:{color};font-weight:bold">{model.status}</span>')

    column_formatters = {
        "status": _status_color,
        "error_msg": lambda v, c, m, p: (
            (m.error_msg[:80] + "...") if m.error_msg and len(m.error_msg) > 80 else m.error_msg or "-"
        ),
    }


# ─── 变更记录管理（只读） ───

class ItemChangeAdmin(AuthModelView):
    """changes 表管理视图 — 只读"""
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True

    column_list = ["id", "item_id", "changed_at", "field_name", "old_value", "new_value"]
    column_sortable_list = ["changed_at"]
    column_default_sort = ("changed_at", True)
    page_size = 50

    column_formatters = {
        "old_value": lambda v, c, m, p: (m.old_value[:60] + "...") if m.old_value and len(m.old_value) > 60 else m.old_value or "-",
        "new_value": lambda v, c, m, p: (m.new_value[:60] + "...") if m.new_value and len(m.new_value) > 60 else m.new_value or "-",
    }


# ─── 执行日志视图 ───

class LogView(BaseView):
    """自定义执行日志查看页面"""

    @expose("/")
    def index(self):
        from web.log_reader import list_log_files, read_log

        file_param = request.args.get("file", "")
        keyword = request.args.get("keyword", "")
        lines_param = request.args.get("lines", 500)

        try:
            max_lines = min(int(lines_param), 5000)
        except (ValueError, TypeError):
            max_lines = 500

        logs = list_log_files()

        content = []
        current_file = file_param
        if file_param:
            if keyword:
                content = read_log(file_param, max_lines, keyword=keyword)
            else:
                content = read_log(file_param, max_lines)
        elif logs:
            current_file = logs[0]["path"]
            content = read_log(current_file, max_lines)

        return self.render(
            "admin/logs.html",
            log_files=logs,
            current_file=current_file,
            content=content,
            keyword=keyword,
            lines=max_lines,
        )


# ─── 任务管控视图 ───

class TaskControlView(BaseView):
    """自定义任务管控页面"""

    @expose("/")
    def index(self):
        return self.render("admin/task_control.html")


# ─── 站点配置管理 ───

class SiteConfigAdmin(AuthModelView):
    """site_configs 表管理视图 — 站点配置 CRUD"""
    can_export = True
    can_view_details = True
    can_set_page_size = True

    column_list = [
        "site_name", "site_url", "search_type", "keywords", "days_back",
        "cron_expr", "enabled", "created_at",
    ]
    column_sortable_list = ["site_name", "enabled", "created_at"]
    column_searchable_list = ["site_name", "site_url", "keywords"]
    column_filters = ["enabled", "search_type"]
    column_default_sort = ("site_name", False)
    page_size = 50

    column_descriptions = {
        "site_name": "站点名称（唯一标识）",
        "site_url": "站点首页地址",
        "search_type": "搜索类型: both/zhaobiao/zhongbiao",
        "keywords": "关键词，逗号分隔多个",
        "days_back": "回溯天数",
        "search_url": "搜索URL模板，支持 {keyword} {start_date} 占位符",
        "cron_expr": "Cron 定时表达式",
        "enabled": "是否启用",
    }

    form_columns = [
        "site_name", "site_url", "search_type", "keywords", "days_back",
        "search_url", "cron_expr", "enabled", "proxy", "notes",
    ]
    form_excluded_columns = ["created_at", "updated_at"]

    column_formatters = {
        "enabled": lambda v, c, m, p: Markup(
            '<span class="badge badge-success">启用</span>' if m.enabled
            else '<span class="badge badge-secondary">禁用</span>'
        ),
        "site_url": lambda v, c, m, p: Markup(
            f'<a href="{m.site_url}" target="_blank">{m.site_url[:50]}...</a>'
            if len(m.site_url) > 50 else f'<a href="{m.site_url}" target="_blank">{m.site_url}</a>'
        ),
    }

    # 导出列
    column_export_list = [
        "site_name", "site_url", "search_type", "keywords", "days_back",
        "search_url", "cron_expr", "enabled", "proxy", "notes",
    ]


# ─── Excel 导入视图 ───

class ExcelImportView(BaseView):
    """Excel 批量导入站点配置"""

    @expose("/", methods=["GET", "POST"])
    def index(self):
        message = None
        result = None

        if request.method == "POST":
            file = request.files.get("excel_file")
            replace_flag = request.form.get("replace_all") == "1"

            if not file or not file.filename:
                message = ("error", "请选择要上传的 Excel 文件")
            else:
                import tempfile
                import os

                # 保存到临时文件
                fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
                os.close(fd)
                file.save(tmp_path)

                try:
                    from utils.site_config_manager import SiteConfigManager
                    mgr = SiteConfigManager()
                    result = mgr.import_from_excel(tmp_path, replace_all=replace_flag)
                    message = (
                        "success",
                        f"导入完成: {result['success']} 成功, "
                        f"{len(result['errors'])} 错误"
                    )
                    if result["errors"]:
                        message = (message[0], message[1] + f" (前3条: {'; '.join(result['errors'][:3])})")
                except Exception as e:
                    message = ("error", f"导入失败: {e}")
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        return self.render(
            "admin/excel_import.html",
            message=message,
            result=result,
        )


# ─── 注册所有视图 ───

def setup_admin(app, db):
    admin = Admin(
        app,
        name="招标爬虫管理",
        index_view=AuthAdminIndexView(
            url="/admin",
            template="admin/index.html",
        ),
        url="/admin",
    )

    # 添加模型视图
    admin.add_view(CrawlItemAdmin(CrawlItem, db.session, name="爬取资料", category="数据管理"))
    admin.add_view(CrawlTaskAdmin(CrawlTask, db.session, name="任务记录", category="数据管理"))
    admin.add_view(ItemChangeAdmin(ItemChange, db.session, name="变更记录", category="数据管理"))
    admin.add_view(SiteConfigAdmin(SiteConfigModel, db.session, name="站点配置", category="数据管理"))

    # 添加自定义视图
    admin.add_view(LogView(name="执行日志", endpoint="logs", category="系统工具"))
    admin.add_view(TaskControlView(name="任务管控", endpoint="task_control", category="系统工具"))
    admin.add_view(ExcelImportView(name="Excel导入", endpoint="excel_import", category="系统工具"))

    return admin
