#!/usr/bin/env python
# encoding:utf-8
# urls.py

__author__ = 'YJX'
__data__ = 2016 / 6 / 23

from transwarp.web import get,view
from models import User, Blog, Comment


@view('test_users.html')
@get('/')
def test_users():
    users = User.find_all()
    return dict(users=users)