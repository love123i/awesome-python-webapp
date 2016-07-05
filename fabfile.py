#!/usr/bin/env python
# encoding:utf-8
# fabfile.py
# 2016/6/30  14:30
# Fabric 自动部署脚本

import os,re
from datetime import datetime

# 导入Fabric API:
from fabric.api import *

'''
Fabric 提供：
    local('  command  ')    在本地执行命令
    run('  command  ')      在远程执行命令
    sudo('  command  ')     (以sudo方式)在远程执行命令
    put('  filepath  ')         上传文件

    with lcd(path):     把当前命令的目录设定为lcd()指定的目录
    with cd(path):      把当前目录在服务器端设置为cd()指定的目录

Fabric 只能运行命令行命令，Windows下可能需要在Cgywin环境下执行该py文件(执行linux命令)
'''

# 服务器登录用户名:
env.user = 'root'
env.password='123456'
# sudo用户为root:
env.sudo_user = 'root'
# 服务器地址，可以有多个，依次部署
env.hosts = ['192.168.253.129']

# 服务器MySQL用户名和口令
db_user = 'root'
db_password = '123456'

# 打包文件
_TAR_FILE = 'dist-awesome.tar.gz'

def build():
    includes = ['static','templates','transwarp','favicon.ico','*.py']
    excludes = ['test','.*','*.pyc','*.pyo']
    # Fabric提供local('...')来运行本地命令
    local('rm -f dist/%s' % _TAR_FILE)
    # with lcd(path)可以把当前命令的目录设定为lcd()指定的目录，注意Fabric只能运行命令行命令，Windows下可能需要Cgywin环境。
    with lcd(os.path.join(os.path.abspath('.'),'www')):
        '''
        --dereference   不建立符号连接，直接复制该连接所指向的原始文件。
        -czvf           c:create  z:gzip压缩  v:verbose  f:file
        '''
        cmd = ['tar','--dereference','-czvf','../dist/%s' % _TAR_FILE]
        cmd.extend(['--exclude=\'%s\'' % ex for ex in excludes])
        cmd.extend(includes)
        local(' '.join(cmd))

# 远程存放临时打包文件的位置
_REMOTE_TMP_TAR = '/tmp/%s' % _TAR_FILE
# 远程工作目录
_REMOTE_BASE_DIR  = '/srv/awesome'

def deploy():
    newdir = 'www-%s' % datetime.now().strftime('%y-%m-%d_%H.%M.%S')
    # 删除已有的tar文件
    run('rm -f %s' % _REMOTE_TMP_TAR)
    # 上传新的tar文件
    put('dist/%s' % _TAR_FILE, _REMOTE_TMP_TAR)
    # 创建新目录
    with cd(_REMOTE_BASE_DIR):
        sudo('mkdir %s' % newdir)
    # 解压到新目录
    with cd('%s/%s' % (_REMOTE_BASE_DIR, newdir)):
        '''
        -xzvf       x:解压  z:gzip压缩  v:verbose  f:file
        '''
        sudo('tar -xzvf %s' % _REMOTE_TMP_TAR)
    # 重置软链接
    with cd(_REMOTE_BASE_DIR):
        sudo('rm -f www')
        sudo('ln -s %s www' % newdir)
        sudo('chown root:root www')
        sudo('chown -R root:root %s' % newdir)
        sudo('chmod 755 www')
        sudo('chmod -R 755 %s' % newdir)
    # 重启Python服务和nginx服务器
    with settings(warn_only=True):
        sudo('supervisorctl stop awesome')
        sudo('supervisorctl start awesome')
        sudo('/etc/init.d/nginx reload')


