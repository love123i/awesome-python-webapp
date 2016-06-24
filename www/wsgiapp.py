#!/usr/bin/env python
# encoding:utf-8
# wsgiapp.py

__author__ = 'YJX'
__data__ = 2016 / 6 / 23

import logging; logging.basicConfig(level=logging.INFO)
import os, time
from datetime import datetime
from transwarp import db
from transwarp.web import WSGIApplication, Jinja2TemplateEngine

from config import configs

# 定义datetime_filter, 输入是t, 输出是unicode字符串
def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60)
    if delta < 86400:
        return u'%小时前' % (delta // 3600)
    if delta < 604800:
        return u'%天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)

# 初始化数据库
db.create_engine(**configs.db)

# 创建一个WSGIApplication:
wsgi = WSGIApplication(os.path.abspath(__file__))
# 初始化jinja2模板引擎
template_engine = Jinja2TemplateEngine(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'))
template_engine.add_filter('datetime', datetime_filter)
wsgi.template_engine = template_engine

# 加载带有@get/@post 的URL处理函数
import urls

wsgi.add_interceptor(urls.user_interceptor)
wsgi.add_interceptor(urls.manage_interceptor)
wsgi.add_module(urls)

# 在9000端口上启动本地测试服务器
if __name__ == '__main__':
    wsgi.run(9000)