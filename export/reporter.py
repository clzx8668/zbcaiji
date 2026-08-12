"""
报告导出
支持 Excel / JSON 格式输出，可按站点、日期、类型筛选。
"""
import json
from pathlib import Path
from typing import Optional
from datetime import datetime
import pandas as pd
from loguru import logger
from config.settings import settings
from core.storage import Storage


class Reporter:
    """报告导出器"""

    def __init__(self, storage: Storage, output_dir: Optional[Path] = None):
        self.storage = storage
        self.output_dir = output_dir or settings.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_excel(
        self,
        site_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        item_type: Optional[str] = None,
        new_only: bool = False,
        filename: Optional[str] = None,
    ) -> Path:
        """
        导出 Excel 报告

        Returns:
            导出文件的路径
        """
        items = self.storage.query_items(
            site_name=site_name,
            item_type=item_type,
            date_from=date_from,
            date_to=date_to,
            new_only=new_only,
            limit=10000,
        )

        if not items:
            logger.warning("无数据可导出")
            return self.output_dir / "empty_report.xlsx"

        df = pd.DataFrame(items)

        # 列名中文化
        column_map = {
            "site_name": "站点名称",
            "title": "公告标题",
            "url": "链接",
            "publish_date": "发布日期",
            "item_type": "公告类型",
            "keywords_matched": "命中关键词",
            "amount": "金额",
            "source_org": "采购单位",
            "detail_text": "内容摘要",
            "first_seen": "首次发现",
            "last_updated": "最后更新",
        }
        df.rename(columns=column_map, inplace=True)

        # 选择输出列
        output_cols = [v for k, v in column_map.items() if v in df.columns]
        df = df[output_cols]

        # 生成文件名
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"bid_report_{timestamp}.xlsx"

        output_path = self.output_dir / filename
        df.to_excel(output_path, index=False, engine="openpyxl")
        logger.info(f"Excel 报告已导出: {output_path} ({len(df)} 条)")
        return output_path

    def export_json(
        self,
        site_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        new_only: bool = False,
        filename: Optional[str] = None,
    ) -> Path:
        """导出 JSON 报告"""
        items = self.storage.query_items(
            site_name=site_name,
            date_from=date_from,
            date_to=date_to,
            new_only=new_only,
            limit=10000,
        )

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"bid_report_{timestamp}.json"

        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"JSON 报告已导出: {output_path} ({len(items)} 条)")
        return output_path

    def get_summary(self, days: int = 7) -> dict:
        """获取汇总统计"""
        return self.storage.get_stats(days=days)

    def print_summary(self, days: int = 7):
        """打印汇总统计到控制台"""
        stats = self.get_summary(days=days)
        print(f"\n{'='*50}")
        print(f"  爬取数据概览（最近 {days} 天）")
        print(f"{'='*50}")
        print(f"  累计条目数: {stats['total_items']}")
        print(f"  最近 {days} 天新增: {stats['recent_items']}")
        print(f"\n  按站点分布:")
        for s in stats.get("by_site", []):
            print(f"    └ {s['site_name']}: {s['cnt']} 条")
        print(f"\n  按类型分布:")
        for t in stats.get("by_type", []):
            print(f"    └ {t.get('item_type', '未知')}: {t['cnt']} 条")
        print(f"{'='*50}\n")
