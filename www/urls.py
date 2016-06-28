#!/usr/bin/env python
# encoding:utf-8
# urls.py

__author__ = 'YJX'
__data__ = 2016 / 6 / 23

from transwarp.web import get, post, view, ctx, interceptor, seeother, notfound
from apis import api, APIError, APIPermissionError, APIResourceNotFoundError, APIValueError
from models import User, Blog, Comment
import re, hashlib, time, logging
from config import configs

_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_MD5 = re.compile(r'^[0-9a-f]{32}$')


_COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret


@view('test_users.html')
@get('/test_users')
def test_users():
    users = User.find_all()
    return dict(users=users)


@api
@post('/api/users')
def register_user():
    print 'POST /api/users'
    i = ctx.request.input(name='', email='', password='')
    name = i.name.strip()
    email = i.email.strip().lower()
    password = i.password
    if not name:
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    # 注意用户口令是客户端传递的经过MD5计算后的32位Hash字符串，所以服务器端并不知道用户的原始口令。
    if not password or not _RE_MD5.match(password):
        raise APIValueError('password')
    user = User.find_first('where email=?', email)
    if user:
        raise APIError('register:failed','email','Email is already in use')
    user = User(name=name, email=email, password=password, image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email).hexdigest())
    user.insert()
    # make session cookies:
    cookie = make_signed_cookie(user.id, user.password, None)
    return user

@view('register.html')
@get('/register')
def register():
    print 'GET: /register'
    return dict()


@api
@get('/api/users')
def api_get_users():
    users = User.find_by('order by created_at desc')
    for u in users:
        u.password = '******'
    return dict(users=users)


@api
@post('/api/authenticate')
def authenticate():
    print 'POST /api/authenticate'
    i = ctx.request.input(remember='')
    email = i.email.strip().lower()
    password = i.password
    remember = i.remember
    user = User.find_first('where email=?', email)
    if user is None:
        raise APIError('auth:failed', 'email', 'Invalid email.')
    elif user.password != password:
        raise APIError('auth:failed', 'password', 'Invalid password.')
    # make session cookie:
    max_age = 604800 if remember=='true' else None
    cookie = make_signed_cookie(user.id, user.password, max_age)
    ctx.response.set_cookie(_COOKIE_NAME, cookie, max_age=max_age)
    user.password = '******'
    return user

# 计算加密MD5
def make_signed_cookie(id, password, max_age):
    expires = str(int(time.time() + (max_age or 86400)))
    L = [id, expires, hashlib.md5('%s-%s-%s-%s' % (id, password, expires, _COOKIE_KEY)).hexdigest()]
    return '-'.join(L)

def parse_signed_cookie(cookie_str):
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        id, expires, md5 = L
        if int(expires) < time.time():
            return None
        user = User.get(id)
        if user is None:
            return None
        if md5 != hashlib.md5('%s-%s-%s-%s' % (id, user.password, expires, _COOKIE_KEY)).hexdigest():
            return None
        return user
    except:
        return None

def check_admin():
    user = ctx.request.user
    if user and user.admin:
        return
    print 'No Admin Permission!!!'
    raise APIPermissionError('No Permission.')

@interceptor('/')
def user_interceptor(next):
    logging.info('try to bind user from session cookie...')
    user = None
    cookie = ctx.request.cookies.get(_COOKIE_NAME)
    if cookie:
        logging.info('parse session cookie...')
        user = parse_signed_cookie(cookie)
        if user:
            logging.info('bind user <%s> to sesion...' % user.email)
    ctx.request.user = user
    return next()



@view('blogs.html')
@get('/')
def index():
    blogs = Blog.find_all()
    return dict(blogs=blogs, user=ctx.request.user)


@view('signin.html')
@get('/signin')
def signin():
    print 'GET /signin'
    return dict()


@get('/signout')
def sigout():
    ctx.response.delete_cookie(_COOKIE_NAME)
    raise seeother('/')


@interceptor('/manage/')
def manage_interceptor(next):
    print 'interceptor /manage'
    user = ctx.request.user
    if user and user.admin:
        return next()
    raise seeother('/signin')


@view('manage_blog_edit.html')
@get('/manage/blogs/create')
def manage_blogs_create():
    return dict(id=None, action='/api/blogs', redirect='/', user=ctx.request.user)


@api
@post('/api/blogs')
def api_create_blog():
    print 'POST: /api/blogs | def api_create_blog()'
    check_admin()
    i = ctx.request.input(name='', summary='', content='')
    name = i.name.strip()
    summary = i.summary.strip()
    content = i.content.strip()
    if not name:
        raise APIValueError('name', 'name cannot be empty.')
    if not summary:
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content:
        raise APIValueError('content', 'content cannot be empty.')
    user = ctx.request.user
    blog = Blog(user_id=user.id, user_name=user.name, name=name, summary=summary, content=content)
    blog.insert()
    print 'blog.insert: %s' % blog
    return blog