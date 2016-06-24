#!/usr/bin/env python
# encoding:utf-8
# urls.py

__author__ = 'YJX'
__data__ = 2016 / 6 / 23

from transwarp.web import get,view
from apis import api
from models import User, Blog, Comment


@view('test_users.html')
@get('/test_users')
def test_users():
    users = User.find_all()
    return dict(users=users)


@view('blogs.html')
@get('/')
def index():
    blogs = Blog.find_all()
    # 查找登陆用户
    user = User.find_first('where email=?','admin@example.com')
    return dict(blogs=blogs, user=user)


@api
@get('/api/users')
def api_get_users():
    users = User.find_by('order by created_at desc')
    # 把用户的口令隐藏掉
    for u in users:
        u.password = '******'
    return dict(users=users)