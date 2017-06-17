#!/usr/bin/env python
# encoding: utf-8

"""
@author: zhanghe
@software: PyCharm
@file: user.py
@time: 2017/3/17 下午11:47
"""
import json
from datetime import datetime

import flask_excel as excel
from flask import Blueprint
from flask import abort
from flask import redirect
from flask import render_template, request, flash
from flask import url_for
from flask_login import current_user, login_required
from itsdangerous import TimestampSigner
from sqlalchemy.orm import aliased

from app_backend.tools.config_manage import get_conf
from app_common.maps import area_code_map
from app_common.maps.type_auth import *
from app_common.tools import md5, json_default
from app_common.tools.date_time import time_local_to_utc
from app_backend import app
from app_backend.api.user import edit_user, user_reg_stats, user_active_stats
from app_backend.api.user_auth import get_user_auth_row, edit_user_auth
from app_backend.api.user_bank import get_user_bank_row_by_id, add_user_bank, edit_user_bank
from app_backend.api.user_profile import get_user_profile_row_by_id, edit_user_profile, get_team_tree_recursion, get_user_profile_row
from app_backend.forms.user import UserProfileForm, UserAuthForm, UserBankForm, UserSearchForm
from app_backend.models import User
from app_backend.models import UserProfile
from app_backend.models import UserBank
from app_backend.models import Wallet
from app_backend.models import Score
from app_backend.models import Bonus
from app_backend.models import BitCoin

from app_common.maps.status_lock import *
from app_common.maps.status_delete import *
from app_common.tools.ip import get_real_ip

from app_backend.permissions import permission_user


SWITCH_EXPORT = get_conf('SWITCH_EXPORT')
PER_PAGE_BACKEND = app.config['PER_PAGE_BACKEND']

bp_user = Blueprint('user', __name__, url_prefix='/user')


@bp_user.route('/list/')
@bp_user.route('/list/<int:page>/')
@login_required
@permission_user.require(http_exception=403)
def lists(page=1):
    """
    会员列表
    """
    form = UserSearchForm(request.form)

    user_id = request.args.get('user_id', '', type=int)
    user_name = request.args.get('user_name', '', type=str)
    start_time = request.args.get('start_time', '', type=str)
    end_time = request.args.get('end_time', '', type=str)
    status_active = request.args.get('status_active', '', type=str)
    status_lock = request.args.get('status_lock', '', type=str)
    op = request.args.get('op', 0, type=int)

    form.user_id.data = user_id
    form.user_name.data = user_name
    form.start_time.data = start_time
    form.end_time.data = end_time
    form.status_active.data = status_active
    form.status_lock.data = status_lock

    search_condition_user = [User.status_delete == STATUS_DEL_NO]
    search_condition_user_profile = []

    # 多次连接同一张表，需要别名
    user_profile_c = aliased(UserProfile)  # 子
    user_profile_p = aliased(UserProfile)  # 父

    if user_id:
        search_condition_user.append(User.id == user_id)
    if start_time:
        search_condition_user.append(User.create_time >= time_local_to_utc(start_time))
    if end_time:
        search_condition_user.append(User.create_time <= time_local_to_utc(end_time))
    if status_active:
        search_condition_user.append(User.status_active == status_active)
    if status_lock:
        search_condition_user.append(User.status_lock == status_lock)
    if user_name:
        search_condition_user_profile.append(user_profile_c.nickname == user_name)
    # 处理导出
    if op == 1:
        if not SWITCH_EXPORT or SWITCH_EXPORT == 'OFF':
            flash(u'导出功能关闭，暂不支持导出', 'warning')
            return redirect(url_for('user.lists'))
        data_list = []
        # query_sets = User.query. \
        #     filter(*search_condition_user). \
        #     outerjoin(UserProfile, User.id == UserProfile.user_id). \
        #     filter(*search_condition_user_profile). \
        #     outerjoin(UserBank, User.id == UserBank.user_id). \
        #     filter(*search_condition_user_bank). \
        #     add_entity(UserProfile). \
        #     add_entity(UserBank). \
        #     all()
        query_sets = User.query. \
            filter(*search_condition_user). \
            outerjoin(user_profile_c, User.id == user_profile_c.user_id). \
            filter(*search_condition_user_profile). \
            outerjoin(user_profile_p, user_profile_c.user_pid == user_profile_p.user_id). \
            outerjoin(Wallet, User.id == Wallet.user_id). \
            outerjoin(BitCoin, User.id == BitCoin.user_id). \
            outerjoin(Score, User.id == Score.user_id). \
            outerjoin(Bonus, User.id == Bonus.user_id). \
            add_entity(user_profile_c). \
            add_entity(user_profile_p). \
            add_entity(Wallet). \
            add_entity(BitCoin). \
            add_entity(Score). \
            add_entity(Bonus). \
            all()
        column_names = [u'用户编号', u'用户名称', u'等级', u'手机号码', u'推荐人', u'钱包余额', u'数字货币', u'积分', u'奖金', u'激活状态', u'锁定状态', u'创建时间']
        data_list.append(column_names)
        for (user, user_profile_c, user_profile_p, wallet, bit_coin, score, bonus) in query_sets:
            row = [
                user.id if user else '',
                user_profile_c.nickname if user_profile_c else '',
                user_profile_c.type_level if user_profile_c else 0,
                user_profile_c.phone if user_profile_c else '',
                user_profile_p.nickname if user_profile_p else '',
                wallet.amount_current if wallet else 0,
                bit_coin.amount if bit_coin else 0,
                score.amount if score else 0,
                bonus.amount if bonus else 0,
                user.status_active if user else 0,
                user.status_lock if user else 0,
                user.create_time if user else ''
            ]
            data_list.append(row)
        return excel.make_response_from_array(
            data_list,
            "csv",
            file_name="用户列表_%s" % datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
    # 处理查询
    pagination = User.query. \
        filter(*search_condition_user). \
        outerjoin(user_profile_c, User.id == user_profile_c.user_id). \
        filter(*search_condition_user_profile). \
        outerjoin(user_profile_p, user_profile_c.user_pid == user_profile_p.user_id). \
        outerjoin(Wallet, User.id == Wallet.user_id). \
        outerjoin(BitCoin, User.id == BitCoin.user_id). \
        outerjoin(Score, User.id == Score.user_id). \
        outerjoin(Bonus, User.id == Bonus.user_id). \
        add_entity(user_profile_c). \
        add_entity(user_profile_p). \
        add_entity(Wallet). \
        add_entity(BitCoin). \
        add_entity(Score). \
        add_entity(Bonus). \
        paginate(page, PER_PAGE_BACKEND, False)

    return render_template(
        'user/list.html',
        title='user_list',
        pagination=pagination,
        form=form,
        STATUS_LOCK_OK=STATUS_LOCK_OK,
        STATUS_DEL_OK=STATUS_DEL_OK,
    )


@bp_user.route('/add/')
@login_required
@permission_user.require(http_exception=403)
def add():
    return render_template('user/add.html', title='user_add')


@bp_user.route('/relationship/')
@login_required
@permission_user.require(http_exception=403)
def relationship():
    """
    全站会员关系结构
    :return:
    """
    form = UserSearchForm(request.form)

    user_id = request.args.get('user_id', '', type=int)
    user_name = request.args.get('user_name', '', type=str)

    if user_name and not user_id:
        user_profile_info = get_user_profile_row(**{'nickname': user_name})
        user_id = user_profile_info.user_id if user_profile_info else 0

    form.user_id.data = user_id
    form.user_name.data = user_name

    # 获取用户团队树形结构
    team_tree = dict(get_team_tree_recursion(user_id or 0))

    return render_template('user/relationship.html', title='user_relationship', form=form, team_tree=team_tree)


@bp_user.route('/auth/<int:user_id>', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def auth(user_id):
    """
    用户登录认证信息
    """
    form = UserAuthForm(request.form)
    condition = {
        'user_id': user_id,
        'type_auth': TYPE_AUTH_ACCOUNT,
    }
    user_auth_info = get_user_auth_row(**condition)
    if request.method == 'GET':
        if user_auth_info:
            form.id.data = user_auth_info.id
            form.user_id.data = user_id
            form.type_auth.data = user_auth_info.type_auth
            form.auth_key.data = user_auth_info.auth_key
            form.auth_secret.data = ''
            form.status_verified.data = user_auth_info.status_verified
            form.create_time.data = user_auth_info.create_time
            form.update_time.data = user_auth_info.update_time
    if request.method == 'POST':
        if form.validate_on_submit():
            # 权限校验
            condition = {
                'id': form.id.data,
                'user_id': user_id,
                'type_auth': TYPE_AUTH_ACCOUNT,
            }
            op_right = get_user_auth_row(**condition)
            if not op_right:
                flash(u'修改失败', 'warning')
                return redirect(url_for('index'))

            current_time = datetime.utcnow()
            user_auth_data = {
                # 'type_auth': TYPE_AUTH_ACCOUNT,
                'auth_key': form.auth_key.data,
                # 'status_verified': form.status_verified.data,
                'update_time': current_time,
            }
            if form.auth_secret.data:
                user_auth_data['auth_secret'] = md5(form.auth_secret.data)
            result = edit_user_auth(form.id.data, user_auth_data)
            if result:
                form.create_time.data = user_auth_info.create_time
                flash(u'修改成功', 'success')
        else:
            form.create_time.data = user_auth_info.create_time
            form.update_time.data = user_auth_info.update_time
            flash(u'修改失败', 'warning')
        # flash(form.errors, 'warning')  # 调试打开

    # flash(u'Hello, %s' % current_user.id, 'info')  # 测试打开
    return render_template('user/auth.html', title='auth', form=form)


@bp_user.route('/bank/<int:user_id>', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def bank(user_id):
    """
    银行信息
    :return:
    """
    form = UserBankForm(request.form)
    bank_info = get_user_bank_row_by_id(user_id)
    if request.method == 'GET':
        form.user_id.data = user_id
        if bank_info:
            form.bank_name.data = bank_info.bank_name
            form.bank_address.data = bank_info.bank_address
            form.bank_account.data = bank_info.bank_account
            form.status_verified.data = bank_info.status_verified
            form.create_time.data = bank_info.create_time
            form.update_time.data = bank_info.update_time
    if request.method == 'POST':
        if form.validate_on_submit():
            current_time = datetime.utcnow()
            bank_data = {
                'bank_name': form.bank_name.data,
                'bank_address': form.bank_address.data,
                'bank_account': form.bank_account.data,
                # 'status_verified': form.status_verified.data,
                'update_time': current_time,
            }
            if bank_info:
                result = edit_user_bank(user_id, bank_data)
            else:
                bank_data['create_time'] = current_time
                result = add_user_bank(bank_data)
            if result:
                # 处理表单时间为空
                form.create_time.data = bank_info.create_time
                flash(u'修改成功', 'success')
        else:
            form.create_time.data = bank_info.create_time
            form.update_time.data = bank_info.update_time
            flash(u'修改失败', 'warning')
        # flash(form.errors, 'warning')  # 调试打开

    # flash(u'Hello, %s' % current_user.id, 'info')  # 测试打开
    return render_template('user/bank.html', title='bank', form=form)


@bp_user.route('/profile/<int:user_id>', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def profile(user_id):
    """
    用户基本信息
    """
    form = UserProfileForm(request.form)
    user_info = get_user_profile_row_by_id(user_id)
    if request.method == 'GET':
        form.user_id.data = user_id
        if user_info:
            form.user_pid.data = user_info.user_pid
            form.nickname.data = user_info.nickname
            form.avatar_url.data = user_info.avatar_url
            form.email.data = user_info.email
            form.area_id.data = user_info.area_id
            form.area_code.data = user_info.area_code
            form.phone.data = user_info.phone
            form.birthday.data = user_info.birthday
            form.id_card.data = user_info.id_card
            form.create_time.data = user_info.create_time
            form.update_time.data = user_info.update_time
    if request.method == 'POST':
        if form.validate_on_submit():
            current_time = datetime.utcnow()
            # 手机号码国际化
            area_id = form.area_id.data
            area_code = area_code_map.get(area_id, '86')
            user_data = {
                'email': form.email.data,
                'area_id': area_id,
                'area_code': area_code,
                'phone': form.phone.data,
                'birthday': form.birthday.data,
                'update_time': current_time,
            }
            result = edit_user_profile(user_id, user_data)
            if result:
                # 处理表单时间为空
                form.create_time.data = user_info.create_time
                flash(u'修改成功', 'success')
        else:
            form.create_time.data = user_info.create_time
            form.update_time.data = user_info.update_time
            flash(u'修改失败', 'warning')
    # flash(form.errors, 'warning')  # 调试打开

    # flash(u'Hello, %s' % current_user.id, 'info')  # 测试打开
    return render_template('user/profile.html', title='profile', form=form)


@bp_user.route('/setting/', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def setting():
    """
    设置
    """
    # return "Hello, World!\nSetting!"
    form = UserProfileForm(request.form)
    if request.method == 'GET':
        from app_backend.api.user import get_user_row_by_id
        user_info = get_user_row_by_id(current_user.id)
        if user_info:
            form.nickname.data = user_info.nickname
            form.avatar_url.data = user_info.avatar_url
            form.email.data = user_info.email
            form.phone.data = user_info.phone
            form.birthday.data = user_info.birthday
            form.create_time.data = user_info.create_time
            form.update_time.data = user_info.update_time
    if request.method == 'POST':
        if form.validate_on_submit():
            # todo 判断邮箱是否重复
            from app_backend.api.user import edit_user
            from datetime import datetime
            user_info = {
                'nickname': form.nickname.data,
                'avatar_url': form.avatar_url.data,
                'email': form.email.data,
                'phone': form.phone.data,
                'birthday': form.birthday.data,
                'update_time': datetime.utcnow(),
                'last_ip': get_real_ip(),
            }
            result = edit_user(current_user.id, user_info)
            if result == 1:
                flash(u'修改成功', 'success')
            if result == 0:
                flash(u'修改失败', 'warning')
        flash(form.errors, 'warning')  # 调试打开
    flash(u'Hello, %s' % current_user.email, 'info')  # 测试打开
    return render_template('./setting.html', title='setting', form=form)


@bp_user.route('/ajax/lock/', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def ajax_lock():
    """
    锁定用户
    :return:
    """
    if request.method == 'GET' and request.is_xhr:
        user_id = request.args.get('user_id', 0, type=int)
        if not user_id:
            return json.dumps({'error': u'锁定失败'})
        current_time = datetime.utcnow()
        user_data = {
            'status_lock': STATUS_LOCK_OK,
            'lock_time': current_time,
            'update_time': current_time
        }
        result = edit_user(user_id, user_data)
        if result == 1:
            return json.dumps({'success': u'锁定成功'})
        if result == 0:
            return json.dumps({'error': u'锁定失败'})
    abort(404)


@bp_user.route('/ajax/unlock/', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def ajax_unlock():
    """
    锁定用户
    :return:
    """
    if request.method == 'GET' and request.is_xhr:
        user_id = request.args.get('user_id', 0, type=int)
        if not user_id:
            return json.dumps({'error': u'解锁失败'})
        current_time = datetime.utcnow()
        user_data = {
            'status_lock': STATUS_LOCK_NO,
            'update_time': current_time
        }
        result = edit_user(user_id, user_data)
        if result == 1:
            return json.dumps({'success': u'解锁成功'})
        if result == 0:
            return json.dumps({'error': u'解锁失败'})
    abort(404)


@bp_user.route('/ajax/del/', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def ajax_delete():
    """
    删除用户
    :return:
    """
    if request.method == 'GET' and request.is_xhr:
        user_id = request.args.get('user_id', 0, type=int)
        if not user_id:
            return json.dumps({'error': u'删除失败'})
        current_time = datetime.utcnow()
        user_data = {
            'status_delete': STATUS_DEL_OK,
            'delete_time': current_time,
            'update_time': current_time
        }
        result = edit_user(user_id, user_data)
        if result == 1:
            return json.dumps({'success': u'删除成功'})
        if result == 0:
            return json.dumps({'error': u'删除失败'})
    abort(404)


# @bp_user.route('/stats/', methods=['GET', 'POST'])
# @login_required
# def stats():
#     """
#     用户统计
#     按日、周、月统计注册量
#     :return:
#     """
#     time_based = request.args.get('time_based', 'date')
#     if time_based not in ['date', 'week', 'month']:
#         time_based = 'date'
#     # 获取注册量，获取激活量
#     return render_template('user/stats.html', title='user_stats')


@bp_user.route('/ajax_stats/', methods=['GET', 'POST'])
@login_required
def ajax_stats():
    """
    获取用户统计
    :return:
    """
    import time
    # time.sleep(3)
    # start_time, end_time, time_based = 'hour'
    time_based = request.args.get('time_based', 'hour')
    result_user_reg = user_reg_stats(time_based)
    result_user_active = user_active_stats(time_based)

    line_chart_data = {
        'labels': [label for label, _ in result_user_reg],
        'datasets': [
            {
                'label': u'注册',
                'backgroundColor': 'rgba(220,220,220,0.5)',
                'borderColor': 'rgba(220,220,220,1)',
                'pointBackgroundColor': 'rgba(220,220,220,1)',
                'pointBorderColor': '#fff',
                'pointBorderWidth': 2,
                'data': [data for _, data in result_user_reg]
            },
            {
                'label': u'激活',
                'backgroundColor': 'rgba(151,187,205,0.5)',
                'borderColor': 'rgba(151,187,205,1)',
                'pointBackgroundColor': 'rgba(151,187,205,1)',
                'pointBorderColor': '#fff',
                'pointBorderWidth': 2,
                'data': [data for _, data in result_user_active]
            }
        ]
    }
    return json.dumps(line_chart_data, default=json_default)


@bp_user.route('/admin_login/<int:user_id>/', methods=['GET', 'POST'])
@login_required
@permission_user.require(http_exception=403)
def admin_login(user_id):
    """
    后台登录前台用户
    :return:
    """
    s = TimestampSigner(app.config.get('ADMIN_TO_USER_LOGIN_SIGN_KEY'))
    user_id_sign = s.sign(str(user_id))
    return redirect('%s/auth/admin_login/?uid_sign=%s' % (app.config.get('FRONTEND_URL', ''), user_id_sign))
