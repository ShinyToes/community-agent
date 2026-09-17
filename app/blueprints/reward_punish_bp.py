from app.utils.security import user_error_message
"""
Reward & Punishment Blueprint — 奖惩记录管理

Routes:
  GET  /                    list_records     — 所有奖惩记录（支持类型筛选）
  GET  /create              create_record    — 新增奖惩记录表单
  POST /create              create_record    — 保存奖惩记录
  GET  /<id>/edit           edit_record      — 编辑奖惩记录
  POST /<id>/edit           edit_record      — 更新奖惩记录
  POST /<id>/delete         delete_record    — 删除奖惩记录
  GET  /stats               stats            — 奖惩统计页面

API:
  GET  /api/stats-summary   stats_summary    — JSON: 类型分布 & 等级分布
  GET  /api/stats-by-month  stats_by_month   — JSON: 当前年份按月统计
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date

from app.extensions import db
from app.models import RewardPunishment, Student, Class
from app.utils.decorators import role_required
from sqlalchemy import func, extract

reward_punish_bp = Blueprint('reward_punish', __name__)


@reward_punish_bp.route('/')
@login_required
def list_records():
    type_filter = request.args.get('type', '').strip()
    query = RewardPunishment.query.order_by(RewardPunishment.rp_date.desc())
    if type_filter:
        query = query.filter(RewardPunishment.type == type_filter)
    # 学生只能看自己的奖惩记录
    if current_user.role == 'student':
        query = query.filter(RewardPunishment.student_id == current_user.related_id)
    # 学生只能看自己的奖惩记录，管理员看全部
    records = query.all()
    return render_template('reward_punish/list.html',
                           records=records,
                           type_filter=type_filter)


@reward_punish_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def create_record():
    if request.method == 'POST':
        try:
            record = RewardPunishment(
                student_id=request.form['student_id'].strip(),
                type=request.form['type'].strip(),
                title=request.form['title'].strip(),
                level=request.form.get('level', '').strip() or None,
                rp_date=datetime.strptime(request.form['rp_date'], '%Y-%m-%d').date(),
                description=request.form.get('description', '').strip() or None,
                evidence=request.form.get('evidence', '').strip() or None,
            )
            db.session.add(record)
            db.session.commit()
            flash('奖惩记录添加成功', 'success')
            return redirect(url_for('reward_punish.list_records'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {user_error_message(e)}', 'danger')

    return render_template('reward_punish/form.html', record=None)


@reward_punish_bp.route('/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_record(record_id):
    record = RewardPunishment.query.get_or_404(record_id)
    if request.method == 'POST':
        try:
            record.student_id = request.form['student_id'].strip()
            record.type = request.form['type'].strip()
            record.title = request.form['title'].strip()
            record.level = request.form.get('level', '').strip() or None
            record.rp_date = datetime.strptime(request.form['rp_date'], '%Y-%m-%d').date()
            record.description = request.form.get('description', '').strip() or None
            record.evidence = request.form.get('evidence', '').strip() or None
            db.session.commit()
            flash('奖惩记录更新成功', 'success')
            return redirect(url_for('reward_punish.list_records'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {user_error_message(e)}', 'danger')

    return render_template('reward_punish/form.html', record=record)


@reward_punish_bp.route('/<int:record_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_record(record_id):
    record = RewardPunishment.query.get_or_404(record_id)
    try:
        db.session.delete(record)
        db.session.commit()
        flash('奖惩记录已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {user_error_message(e)}', 'danger')
    return redirect(url_for('reward_punish.list_records'))


@reward_punish_bp.route('/stats')
@login_required
@role_required('admin')
def stats():
    return render_template('reward_punish/stats.html')


# ---- API Endpoints ----

@reward_punish_bp.route('/api/stats-summary')
@login_required
@role_required('admin')
def stats_summary():
    """返回类型分布和等级分布的统计数据。"""

    # 类型分布 (奖励 vs 惩罚)
    type_counts = db.session.query(
        RewardPunishment.type,
        func.count(RewardPunishment.record_id)
    ).group_by(RewardPunishment.type).all()
    type_map = dict(type_counts)

    type_labels = ['奖励', '惩罚']
    type_values = [type_map.get('奖励', 0), type_map.get('惩罚', 0)]

    # 等级分布
    level_counts = db.session.query(
        RewardPunishment.level,
        func.count(RewardPunishment.record_id)
    ).group_by(RewardPunishment.level).all()

    level_labels = [r[0] or '未知' for r in level_counts]
    level_values = [r[1] for r in level_counts]

    return jsonify({
        'type_labels': type_labels,
        'type_values': type_values,
        'level_labels': level_labels,
        'level_values': level_values,
    })


@reward_punish_bp.route('/api/stats-by-month')
@login_required
@role_required('admin')
def stats_by_month():
    """返回当前年份按月统计的奖惩记录数量。"""
    current_year = date.today().year
    monthly = db.session.query(
        extract('month', RewardPunishment.rp_date).label('month'),
        func.count(RewardPunishment.record_id)
    ).filter(
        extract('year', RewardPunishment.rp_date) == current_year
    ).group_by('month').order_by('month').all()

    month_map = dict(monthly)

    month_names = ['1月', '2月', '3月', '4月', '5月', '6月',
                   '7月', '8月', '9月', '10月', '11月', '12月']
    values = [month_map.get(i, 0) for i in range(1, 13)]

    return jsonify({
        'labels': month_names,
        'values': values,
    })