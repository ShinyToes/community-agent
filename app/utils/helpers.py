from datetime import datetime, date
from markupsafe import Markup


def format_date(d, fmt='%Y-%m-%d'):
    if d is None:
        return ''
    if isinstance(d, (datetime, date)):
        return d.strftime(fmt)
    return str(d)


def format_datetime(dt, fmt='%Y-%m-%d %H:%M'):
    if dt is None:
        return ''
    if isinstance(dt, datetime):
        return dt.strftime(fmt)
    return str(dt)


def get_status_badge(status):
    """根据状态返回 Bootstrap 徽章 HTML"""
    badges = {
        '在读': 'success',
        '休学': 'warning',
        '退学': 'danger',
        '毕业': 'info',
        '肄业': 'secondary',
        '待审批': 'warning',
        '已通过': 'success',
        '已拒绝': 'danger',
        '在修': 'primary',
        '未通过': 'danger',
        '退课': 'secondary',
        '正常': 'success',
        '补考': 'warning',
        '重修': 'danger',
        '奖励': 'success',
        '惩罚': 'danger',
        '健康': 'success',
        '良好': 'info',
        '一般': 'warning',
        '较差': 'danger',
    }
    color = badges.get(status, 'secondary')
    return Markup('<span class="badge bg-{}">{}</span>').format(color, status)
