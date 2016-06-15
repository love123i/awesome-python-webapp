#!/usr/bin/env python
# encoding:utf-8
__author__ = 'YJX'
__data__ = 2016 / 6 / 13

import threading
import functools, logging, time, uuid

class  Dict(dict):
	'''
	简单的dict，但是支持
		1、以 x.y 方式来访问 key,value
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
	    Return next id as 50-char string.
	    Args:
	        t: unix timestamp, default to None and using time.time().
	    '''
	if t is None:
		t = time.time()
	return '%015d%s000' % (int(t * 1000), uuid.uuid4().hex)



def _profiling(start, sql=''):
	'''
	用于记录 事务处理 所消耗的时间，并记录过于耗时的SQL语句
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


class _DbCtx(threading.local):
	'''
	持有数据库连接的上下文对象
    Thread local object that holds connection info.
    '''
	def __init__(self):
		self.connection = None
		self.transactions = 0

	def is_init(self):
		return self.connection is not None

	def init(self):
		logging.info('open lazy connection...')
		self.connection = _LasyConnection()
		self.transactions = 0

	def cleanup(self):
		self.connection.cleanup()
		self.connection = None

	def cursor(self):
		return self.connection.cursor()


# thread-local db context
# _db_ctx是 threadlocal 对象，所以，它持有的数据库连接对于每个线程看到的都是不一样的。任何一个线程都无法访问到其他线程持有的数据库连接。
_db_ctx = _DbCtx()

engine = None

#数据库引擎对象：
class _Engine(object):
	def __init__(self, connect):
		self._connect = connect

	def connect(self):
		return self._connect()


def create_engine(user, password, database, host='127.0.0.1', port=3306, **kw):
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
	'''
	定义了__enter__()和__exit__()的对象可以用于with语句，确保任何情况下__exit__()方法可以被调用。

	把_ConnectionCtx的作用域作用到一个函数调用上，可以这么写：
	with connection():
     do_some_db_operation()
	但是更简单的写法是写个@decorator：
	@with_connection
	def do_some_db_operation():
        pass
	'''

	def __enter__(self):
		global _db_ctx
		self.should_cleanup = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_cleanup = True
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		global _db_ctx
		if self.should_cleanup:
			_db_ctx.cleanup()


def connection():
	'''
    返回 _ConnectionCtx object，它可以用于 'with' 语法：

    with connection():
        pass
    '''
	return _ConnectionCtx()



def with_connection(func):
	'''
	注意到Connection对象是存储在_DbCtx这个threadlocal对象里的，
	因此，嵌套使用with connection()也没有问题。
	_DbCtx永远检测当前是否已存在Connection，
		如果存在，直接使用，
		如果不存在，则打开一个新的Connection。
	'''
	@functools.wraps(func)
	def _wrapper(*args, **kw):
		with _ConnectionCtx():
			return func(*args, **kw)
	return _wrapper



class _TransactionCtx(object):
	'''
    _TransactionCtx object that can handle transactions.

    with _TransactionCtx():
        pass
    '''

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
    Create a transaction object so can use with statement:

    with transaction():
        pass

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
    A decorator that makes function around transaction.
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
	# 执行 select SQL语句，并返回 unique result 或 list result
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
    Execute select SQL and expected one result.
    If no result found, return None.
    If multiple results found, the first one returned.
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
    Execute select SQL and expected one int and only one int result.
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
    Execute insert SQL.
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
	result = _update(sql, *args)

	logging.info('[insert] sql= %s, args= %s,result= %s' % (sql, args, result))

	return result




def update(sql, *args):
	r'''
    Execute update SQL.
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