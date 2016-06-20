#!/usr/bin/env python
# encoding:utf-8
__author__ = 'YJX'
__data__ = 2016 / 6 / 13

'''
设计db模块的原因：
  1. 更简单的操作数据库
      一次数据访问：   数据库连接 => 游标对象 => 执行SQL => 处理异常 => 清理资源。
      db模块对这些过程进行封装，使得用户仅需关注SQL执行。
  2. 数据安全
      用户请求以多线程处理时，为了避免多线程下的数据共享引起的数据混乱，
      需要将数据连接以ThreadLocal对象传入。
设计db接口：
  1.设计原则：
      根据上层调用者设计简单易用的API接口
  2. 调用接口
      1. 初始化数据库连接信息
          create_engine封装了如下功能:
              1. 为数据库连接 准备需要的配置信息
              2. 创建数据库连接(由生成的全局对象engine的 connect方法提供)
          from transwarp import db
          db.create_engine(user='root',
                           password='password',
                           database='test',
                           host='127.0.0.1',
                           port=3306)
      2. 执行SQL DML (DML：数据库操纵语言)
          select 函数封装了如下功能:
              1.支持一个数据库连接里执行多个SQL语句
              2.支持链接的自动获取和释放
          使用样例:
              users = db.select('select * from user')
              # users =>
              # [
              #     { "id": 1, "name": "Michael"},
              #     { "id": 2, "name": "Bob"},
              #     { "id": 3, "name": "Adam"}
              # ]
      3. 支持事物
         transaction 函数封装了如下功能:
             1. 事务也可以嵌套，内层事务会自动合并到外层事务中，这种事务模型足够满足99%的需求
'''

import threading
import functools, logging, time, uuid

class  Dict(dict):
	'''
	简单的dict，但是支持
		1、支持通过属性访问，即以 x.y 方式来访问 key,value
		2、支持 Dict(iterable,iterable)方式进行初始化,会自动一一对应生成dict
    >>> d1 = Dict()
    >>> d1['x'] = 100
    >>> d1.x
    100
    >>> d1.y = 200
    >>> d1['y']
    200
    >>> d2 = Dict(a=1, b=2, c='3')
    >>> d2.c
    '3'
    >>> d2['empty']
    Traceback (most recent call last):
        ...
    KeyError: 'empty'
    >>> d2.empty
    Traceback (most recent call last):
        ...
    AttributeError: 'Dict' object has no attribute 'empty'
    >>> d3 = Dict(('a', 'b', 'c'), (1, 2, 3))
    >>> d3.a
    1
    >>> d3.b
    2
    >>> d3.c
    3
    '''
	def __init__(self, names=(), values=(), **kw):
		super(Dict, self).__init__(**kw)
		for k,v in zip(names, values):
			self[k] = v

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

	def __setattr__(self, key, value):
		self[key] = value



def next_id(t=None):
	'''
    生成一个唯一id，由  【当前时间戳】+【UUID随机数】 拼接得到
    '''
	if t is None:
		t = time.time()
	return '%015d%s000' % (int(t * 1000), uuid.uuid4().hex)



def _profiling(start, sql=''):
	'''
	用于剖析sql的执行时间
	'''
	t = time.time() - start
	if t > 0.1:
		logging.warning('[PROFILING] [DB] %s: %s' % (t, sql))
	else:
		logging.info('[PROFILING] [DB] %s: %s' % (t,sql))



class DBError(Exception):
	pass



class MultiColumnsError(DBError):
	pass



class _LasyConnection(object):
	"""
    惰性连接对象
    仅当需要cursor对象时，才连接数据库，获取连接
    """

	def __init__(self):
		self.connection = None

	def cursor(self):
		if self.connection is None:
			connection = engine.connect()   #此处返回的是 lambda: mysql.connector.connect(**params)
			logging.info('open connection <%s>...' % hex(id(connection)))   # hex: int -> 16进制 int
			self.connection = connection
		return self.connection.cursor()

	def commit(self):
		self.connection.commit()

	def rollback(self):
		self.connection.rollback()

	def cleanup(self):
		if self.connection:
			connection = self.connection
			self.connection = None
			logging.info('close connection <%s>...' % hex(id(connection)))
			connection.close()


class (threading.local):
	"""
    db模块的核心对象, 数据库连接的上下文对象，负责从数据库获取和释放连接
    取得的连接是惰性连接对象，因此只有调用cursor对象时，才会真正获取数据库连接
    该对象是一个 Thread local对象，因此绑定在此对象上的数据 仅对本线程可见
    """
	def __init__(self):
		self.connection = None
		self.transactions = 0

	def is_init(self):
		"""
        返回一个布尔值，用于判断 此对象的初始化状态
        """
		return self.connection is not None

	def init(self):
		"""
        初始化连接的上下文对象，获得一个惰性连接对象
        """
		logging.info('open lazy connection...')
		self.connection = _LasyConnection()
		self.transactions = 0

	def cleanup(self):
		"""
        清理连接对象，关闭连接
        """
		self.connection.cleanup()
		self.connection = None

	def cursor(self):
		"""
        获取cursor对象， 真正取得数据库连接
        """
		return self.connection.cursor()


# thread-local db context
# _db_ctx是 threadlocal 对象，所以，它持有的数据库连接对于每个线程看到的都是不一样的。任何一个线程都无法访问到其他线程持有的数据库连接。
_db_ctx = _DbCtx()


engine = None


class _Engine(object):
	"""
	数据库引擎对象
	用于保存 db模块的核心函数：create_engine 创建出来的数据库连接
	"""
	def __init__(self, connect):
		self._connect = connect

	def connect(self):
		return self._connect()


def create_engine(user, password, database, host='127.0.0.1', port=3306, **kw):
	'''
	db模型的核心函数，用于连接数据库，生成全局对象engine
	engine对象持有数据库连接

	封装功能：
		1. 为数据库连接 准备需要的配置信息
		2. 创建数据库连接（由生成的全局对象engine的 connect方法提供
	from transwarp import db
    db.create_engine(user='root',
					 password='password',
					 database='test',
				     host='127.0.0.1',
				     port=3306)
	'''
	import mysql.connector
	global engine
	if engine is not None:
		raise DBError('Engine is already initialized.')
	params = dict(user=user, password=password, database=database, host=host, port=port)
	defaults = dict(use_unicode=True, charset='utf8', collation='utf8_general_ci', autocommit=False)
	for k,v in defaults.iteritems():
		params[k] = kw.pop(k,v)
	params.update(kw)
	params['buffered'] = True
	engine = _Engine(lambda: mysql.connector.connect(**params))
	#test connection...
	logging.info('Init mysql engine <%s> ok.' % hex(id(engine)))



#数据库连接的上下文，目的是自动获取和释放连接
class _ConnectionCtx(object):
	"""
	因为_DbCtx实现了连接的 获取和释放，但是并没有实现连接
	的自动获取和释放，_ConnectCtx在 _DbCtx基础上实现了该功能，
	因此可以对 _ConnectCtx 使用with 语法，比如：
	with connection():
		pass
		with connection():
			pass
	"""

	def __enter__(self):
		"""
		获取一个惰性连接对象
		"""
		global _db_ctx
		self.should_cleanup = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_cleanup = True
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		"""
		释放连接
		"""
		global _db_ctx
		if self.should_cleanup:
			_db_ctx.cleanup()


def connection():
	'''
    db模块核心函数，用于获取一个数据库连接
    通过_ConnectionCtx对 _db_ctx封装，使得惰性连接可以自动获取和释放
    也就是可以使用with语法来处理数据库连接

    _ConnectionCtx      实现with语法
    ^
    |
    _db_ctx             _DbCtx实例
    ^
    |
    _DbCtx              获取和释放惰性连接, threading.local类
    ^
    |
    _LasyConnection     实现惰性连接
    '''
	return _ConnectionCtx()



def with_connection(func):
	'''
	设计一个装饰器 替换with语法，让代码更优雅
	比如:
	    @with_connection
	    def foo(*args, **kw):
	        f1()
	        f2()
	        f3()
	'''
	@functools.wraps(func)
	def _wrapper(*args, **kw):
		with _ConnectionCtx():
			return func(*args, **kw)
	return _wrapper



class _TransactionCtx(object):
	"""
	事务嵌套比Connection嵌套复杂一点，因为事务嵌套需要计数，
	每遇到一层嵌套就+1，离开一层嵌套就-1，最后到0时提交事务
	"""

	def __enter__(self):
		global _db_ctx
		self.should_close_conn = False
		if not _db_ctx.is_init():
			# needs open a connection first:
			_db_ctx.init()
			self.should_close_conn = True
		_db_ctx.transactions = _db_ctx.transactions + 1
		logging.info('begin transaction...' if _db_ctx.transactions == 1 else 'join current transaction...')
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		global _db_ctx
		_db_ctx.transactions = _db_ctx.transactions - 1
		try:
			if _db_ctx.transactions == 0:
				if exc_type is None:
					self.commit()
				else:
					self.rollback()
		finally:
			if self.should_close_conn:
				_db_ctx.cleanup()

	def commit(self):
		global _db_ctx
		logging.info('commit transaction...')
		try:
			_db_ctx.connection.commit()
			logging.info('commit ok.')
		except:
			logging.warning('commit failed. try rollback...')
			_db_ctx.connection.rollback()
			logging.warning('rollback ok.')
			raise

	def rollback(self):
		global _db_ctx
		logging.warning('rollback transaction...')
		_db_ctx.connection.rollback()
		logging.info('rollback ok.')

def transaction():
	'''
	db模块核心函数 用于实现事物功能
    支持事物:
        with db.transaction():
            db.select('...')
            db.update('...')
            db.update('...')
    支持事物嵌套:
        with db.transaction():
            transaction1
            transaction2
            ...

    >>> def update_profile(id, name, rollback):
    ...     u = dict(id=id, name=name, email='%s@test.org' % name, passwd=name, last_modified=time.time())
    ...     insert('user', **u)
    ...     r = update('update user set passwd=? where id=?', name.upper(), id)
    ...     if rollback:
    ...         raise StandardError('will cause rollback...')
    >>> with transaction():
    ...     update_profile(900301, 'Python', False)
    >>> select_one('select * from user where id=?', 900301).name
    u'Python'
    >>> with transaction():
    ...     update_profile(900302, 'Ruby', True)
    Traceback (most recent call last):
      ...
    StandardError: will cause rollback...
    >>> select('select * from user where id=?', 900302)
    []
    '''
	return _TransactionCtx()

def with_transaction(func):
	'''
	设计一个装饰器 替换with语法，让代码更优雅
    比如:
        @with_transaction
        def do_in_transaction():

    >>> @with_transaction
    ... def update_profile(id, name, rollback):
    ...     u = dict(id=id, name=name, email='%s@test.org' % name, passwd=name, last_modified=time.time())
    ...     result = insert('user', **u)
    ...     r = update('update user set passwd=? where id=?', name.upper(), id)
    ...     if rollback:
    ...         raise StandardError('will cause rollback...')
    >>> update_profile(8080, 'Julia', False)
    >>> select_one('select * from user where id=?', 8080).passwd
    u'JULIA'
    >>> update_profile(9090, 'Robert', True)
    Traceback (most recent call last):
      ...
    StandardError: will cause rollback...
    >>> select('select * from user where id=?', 9090)
    []
    '''
	@functools.wraps(func)
	def _wrapper(*args, **kw):
		_start = time.time()
		with _TransactionCtx():
			func(*args, **kw)
		_profiling(_start)
	return _wrapper


def _select(sql, first, *args):
	"""
    执行SQL，返回一个结果 或者多个结果组成的列表
    """
	global _db_ctx
	cursor = None
	sql = sql.replace('?','%s')
	logging.info('SQL: %s, ARGS: %s' % (sql, args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql, args)
		if cursor.description: # cursor.description只用于select语句，返回一行的列名
			names = [x[0] for x in cursor.description]
		if first:
			values = cursor.fetchone()
			if not values:
				return None
			return Dict(names, values)
		return [Dict(names,x) for x in cursor.fetchall()]
	finally:
		if cursor:
			cursor.close()


@with_connection
def select_one(sql, *args):
	'''
    执行SQL 仅返回一个结果
    如果没有结果 返回None
    如果有1个结果，返回一个结果
    如果有多个结果，返回第一个结果

    >>> u1 = dict(id=100, name='Alice', email='alice@test.org', passwd='ABC-12345', last_modified=time.time())
    >>> u2 = dict(id=101, name='Sarah', email='sarah@test.org', passwd='ABC-12345', last_modified=time.time())
    >>> insert('user', **u1)
    1
    >>> insert('user', **u2)
    1
    >>> u = select_one('select * from user where id=?', 100)
    >>> u.name
    u'Alice'
    >>> select_one('select * from user where email=?', 'abc@email.com')
    >>> u2 = select_one('select * from user where passwd=? order by email', 'ABC-12345')
    >>> u2.name
    u'Alice'
    '''
	return _select(sql, True, *args)


@with_connection
def select_int(sql, *args):
	'''
    执行一个sql 返回一个数值，
    注意仅一个数值，如果返回多个数值将触发异常

    >>> n = update('delete from user')
    >>> u1 = dict(id=96900, name='Ada', email='ada@test.org', passwd='A-12345', last_modified=time.time())
    >>> u2 = dict(id=96901, name='Adam', email='adam@test.org', passwd='A-12345', last_modified=time.time())
    >>> insert('user', **u1)
    1
    >>> insert('user', **u2)
    1
    >>> select_int('select count(*) from user')
    2
    >>> select_int('select count(*) from user where email=?', 'ada@test.org')
    1
    >>> select_int('select count(*) from user where email=?', 'notexist@test.org')
    0
    >>> select_int('select id from user where email=?', 'ada@test.org')
    96900
    >>> select_int('select id, name from user where email=?', 'ada@test.org')
    Traceback (most recent call last):
        ...
    MultiColumnsError: Expect only one column.
    '''
	d = _select(sql, True, *args)
	if len(d) != 1:
		raise MultiColumnsError('Expect only one column.')
	return  d.values()[0]



@with_connection
def select(sql, *args):
	'''
	执行sql 以列表形式返回结果

	select 函数封装了如下功能：
		1. 支持一个数据库连接里执行多个SQL语句
		2. 支持链接的自动获取和释放
	使用样例:
		users = db.select('select * from user')
		# users =>
		# [
		#     { "id": 1, "name": "Michael"},
		#     { "id": 2, "name": "Bob"},
		#     { "id": 3, "name": "Adam"}
		# ]

    Execute select SQL and return list or empty list if no result.
    >>> u1 = dict(id=200, name='Wall.E', email='wall.e@test.org', passwd='back-to-earth', last_modified=time.time())
    >>> u2 = dict(id=201, name='Eva', email='eva@test.org', passwd='back-to-earth', last_modified=time.time())
    >>> insert('user', **u1)
    1
    >>> insert('user', **u2)
    1
    >>> L = select('select * from user where id=?', 900900900)
    >>> L
    []
    >>> L = select('select * from user where id=?', 200)
    >>> L[0].email
    u'wall.e@test.org'
    >>> L = select('select * from user where passwd=? order by id desc', 'back-to-earth')
    >>> L[0].name
    u'Eva'
    >>> L[1].name
    u'Wall.E'
    '''
	return _select(sql, False, *args)


@with_connection
def _update(sql, *args):
	'''
    执行update 语句，返回update的行数
    '''
	global _db_ctx
	cursor = None
	sql = sql.replace('?', '%s')
	logging.info('SQL: %s, ARGS: %s' % (sql, args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql, args)
		r = cursor.rowcount
		if _db_ctx.transactions==0:
			# no transaction enviroment:
			logging.info('auto commit')
			_db_ctx.connection.commit()
		return r
	finally:
		if cursor:
			cursor.close()


def insert(table, **kw):
	'''
    执行insert语句

    >>> u1 = dict(id=2000, name='Bob', email='bob@test.org', passwd='bobobob', last_modified=time.time())
    >>> insert('user', **u1)
    1
    >>> u2 = select_one('select * from user where id=?', 2000)
    >>> u2.name
    u'Bob'
    >>> insert('user', **u2)
    Traceback (most recent call last):
      ...
    IntegrityError: 1062 (23000): Duplicate entry '2000' for key 'PRIMARY'
    '''
	cols, args = zip(*kw.iteritems())
	sql = 'insert into `%s` (%s) values (%s)' % (table, ','.join(['`%s`' % col for col in cols]), ','.join(['?' for i in range(len(cols))]))
	print 'insert: %s, args: %s' % (sql,args)
	result = _update(sql, *args)

	logging.info('[insert] sql= %s, args= %s,result= %s' % (sql, args, result))

	return result




def update(sql, *args):
	r'''
    执行update 语句，返回update的行数

    >>> u1 = dict(id=1000, name='Michael', email='michael@test.org', passwd='123456', last_modified=time.time())
    >>> insert('user', **u1)
    1
    >>> u2 = select_one('select * from user where id=?', 1000)
    >>> u2.email
    u'michael@test.org'
    >>> u2.passwd
    u'123456'
    >>> update('update user set email=?, passwd=? where id=?', 'michael@example.org', '654321', 1000)
    1
    >>> u3 = select_one('select * from user where id=?', 1000)
    >>> u3.email
    u'michael@example.org'
    >>> u3.passwd
    u'654321'
    >>> update('update user set passwd=? where id=?', '***', '123\' or id=\'456')
    0
    '''
	result = _update(sql, *args)

	logging.info('[update] sql= %s, args= %s,result= %s' % (sql, args, result))

	return result



if __name__=='__main__':
	logging.basicConfig(level=logging.DEBUG)
	create_engine('root','123456','test')
	update('drop table if exists user')
	update('create table user(id int primary key, name text, email text, passwd text, last_modified real)')
	import doctest
	doctest.testmod()