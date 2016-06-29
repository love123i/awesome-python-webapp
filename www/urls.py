#!/usr/bin/env python
# encoding:utf-8
# urls.py

__author__ = 'YJX'
__data__ = 2016 / 6 / 23

from transwarp.web import get, post, view, ctx, interceptor, seeother, notfound
from apis import Page, api, APIError, APIPermissionError, APIResourceNotFoundError, APIValueError
from models import User, Blog, Comment
import re, hashlib, time, logging
from config import configs
import markdown2

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
    '''创建用户 POST API'''
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
    ctx.response.set_cookie(_COOKIE_NAME, cookie)
    return user

@view('register.html')
@get('/register')
def register():
    '''创建用户 GET VIEW'''
    return dict()


@api
@get('/api/users')
def api_get_users():
    '''获取用户 GET API'''
    total = User.count_all()
    page = Page(total, _get_page_index())
    users = User.find_by('order by created_at desc limit ?,?', page.offset, page.limit)
    for u in users:
        u.password = '******'
    return dict(users=users, page=page)


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


def _get_page_index():
    page_index = 1
    try:
        page_index = int(ctx.request.get('page',1))
    except ValueError:
        pass
    return page_index

def _get_blogs_by_page():
    total = Blog.count_all()
    page = Page(total, _get_page_index())
    blogs = Blog.find_by('order by created_at desc limit ?,?', page.offset, page.limit)
    return blogs, page


@api
@get('/api/blogs')
def api_get_blogs():
    '''获取日志 API'''
    format = ctx.request.get('format','')
    blogs, page = _get_blogs_by_page()
    if format == 'html':
        for blog in blogs:
            blog.content = markdown2.markdown(blog.content)
    return dict(blogs=blogs, page=page)


@api
@get('/api/blogs/:blog_id')
def api_get_blog(blog_id):
    '''日志详情页 GET API'''
    blog = Blog.get(blog_id)
    if blog:
        return blog
    raise APIResourceNotFoundError('Blog')



@api
@post('/api/blogs/:blog_id/delete')
def api_delete_blog(blog_id):
    '''删除日志 POST API'''
    check_admin()
    blog = Blog.get(blog_id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    blog.delete()
    return dict(id=blog_id)


@api
@get('/api/comments')
def api_get_comments():
    '''创建评论 GET API'''
    total = Comment.count_all()
    page = Page(total, _get_page_index())
    comments = Comment.find_by('order by created_at desc limit ?,?', page.offset, page.limit)
    return dict(comments=comments, page=page)


@api
@post('/api/comments/:comment_id/delete')
def api_delete_comment(comment_id):
    '''删除评论 POST API'''
    check_admin()
    comment = Comment.get(comment_id)
    if comment is None:
        raise APIResourceNotFoundError('Comment')
    comment.delete()
    return dict(id=comment_id)



@api
@post('/api/blogs/:blog_id/comments')
def api_create_blog_comments(blog_id):
    '''创建评论 POST API'''
    user = ctx.request.user
    if user is None:
        raise APIPermissionError('Need signin.')
    blog = Blog.get(blog_id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    content = ctx.request.input(content='').content.strip()
    if not content:
        raise APIValueError('content')
    c = Comment(blog_id=blog_id, user_id=user.id, user_name=user.name, user_image=user.image, content=content)
    c.insert()
    return dict(comment=c)


@view('blogs.html')
@get('/')
def index():
    '''主页--博客列表 GET VIEW'''
    blogs, page = _get_blogs_by_page()
    return dict(page=page, blogs=blogs, user=ctx.request.user)


@view('blog.html')
@get('/blog/:blog_id')
def blog(blog_id):
    blog = Blog.get(blog_id)
    if blog is None:
        raise notfound()
    blog.html_content = markdown2.markdown(blog.content)
    comments = Comment.find_by('where blog_id=? order by created_at desc limit 1000', blog_id)
    return dict(blog=blog, comments=comments, user=ctx.request.user)

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


@api
@post('/api/blogs')
def api_create_blog():
    '''创建日志 POST API'''
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


@api
@post('/api/blogs/:blog_id')
def api_update_blog(blog_id):
    '''修改日志 POST API'''
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
    blog = Blog.get(blog_id)
    blog.name = name
    blog.summary = summary
    blog.content = content
    blog.update()
    return blog


@view('manage_blog_edit.html')
@get('/manage/blogs/create')
def manage_blogs_create():
    '''管理_创建日志页 GET VIEW'''
    return dict(id=None, action='/api/blogs', redirect='/manage/blogs', user=ctx.request.user)


@view('manage_blog_edit.html')
@get('/manage/blogs/edit/:blog_id')
def manage_blogs_edit(blog_id):
    '''管理_修改日志页 GET VIEW'''
    blog = Blog.get(blog_id)
    if blog is None:
        raise notfound()
    print 'GET VIEW /manage/blogs/edit/:blog_id dict = %s' % dict(id=blog.id, name=blog.name, summary=blog.summary, content=blog.content, action='/api/blogs/%s' % blog_id, redirect='/manage/blogs', user=ctx.request.user)
    return dict(id=blog.id, name=blog.name, summary=blog.summary, content=blog.content, action='/api/blogs/%s' % blog_id, redirect='/manage/blogs', user=ctx.request.user)


@get('/manage/')
def manage_index():
    raise seeother('/manage/comments')


@view('manage_user_list.html')
@get('/manage/users')
def manage_user():
    return dict(page_index=_get_page_index(), user=ctx.request.user)


@view('manage_comment_list.html')
@get('/manage/comments')
def manage_comments():
    '''管理_评论列表页 GET VIEW'''
    return dict(page_index=_get_page_index(), user=ctx.request.user)


@view('manage_blog_list.html')
@get('/manage/blogs')
def manage_blogs():
    '''管理_日志列表页 GET VIEW'''
    return dict(page_index=_get_page_index(), user=ctx.request.user)

