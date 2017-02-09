#!/usr/bin /python
# -*- coding: utf-8 -*-

"""
设计db模块的原因:
	1.更简单的操作数据库
		封装 数据库连接=>游标对象=>执行对象=>处理异常=>清理资源 的过程
		使用户仅需关注sql语句的执行
	2.数据安全
		用户请求多线程处理时,为了避免数据共享引起数据混乱,
		需要将数据连接以ThreadLocal对象传入
设计db接口:
	1.设计原则
		根据上层调用者设计简单易用的API接口
	2.调用接口
		1.初始化数据库连接信息
			create_engine封装了下面功能:
			1.为数据库连接准备需要的配置信息
			2.创建数据库连接(由生成的全局对象engine的connect方法提供)
			使用样例:
			from transwarp import db
			db.create_engine(user = 'user',
							password = 'password',
							database = 'database',
							host = '127.0.0.1',
								port = 3306)
		2.执行SQL DML
			select函数封装了如下功能
			1.支持一个数据库连接里执行多个sql语句
			2.支持连接的自动获取与释放
			使用样例:
			users = db.select('select * from user')
			#users =>
			#[
			#  {"id":1,"name":"A"},
			#  {"id":2,"name":"B"},
			#  {"id":3,"name":"C"}
			#]
		3.支持事务
			transaction函数封装了如下功能:
			1.事务也可以嵌套,内层事务会自动合并到外层事务中,这种事务能满足99%的需求
"""
import functools
import threading
import time
import uuid
import logging

def next_id(t=None):
	"""
	生成一个唯一id   由 当前时间 + 随机数（由伪随机数得来）拼接得到
	"""
	if t is None:
		t = time.time()
	return '%015d%s000' % (int(t * 1000), uuid.uuid4().hex)


def _profiling(start, sql=''):
	"""
	用于剖析sql的执行时间
	"""
	t = time.time() - start
	if t > 0.1:
		logging.warning('[PROFILING] [DB] %s: %s' % (t, sql))
	else:
		logging.info('[PROFILING] [DB] %s: %s' % (t, sql))

#global engine object:
engine = None

def create_engine(user,password,database,host,port = 3306,**kw):
	"""
	db模型的核心函数,用于连接数据库,生成全局对象engine
	engine对象持有数据库连接
	"""
	import mysql.connector
	global engine
	if engine is not None:
		raise DBError('Engine si already initialized.')
	params = dict(user = user,password = password,database = database,host = host,port = port)
	defaults = dict(use_unicode = True,charset = 'utf8',collation='utf8_general_ci',autocommit=False)
	for k,v in defaults.iteritems():
		params[k] = kw.pop(k,v)
	params.update(kw)
	params['buffered'] = True
	engine = _Engine(lambda:mysql.connector.connect(**params))
	logging.info('Init mysql engine <%s> ok.' % hex(id(engine)))


class _Engine(object):
	"""
	数据库引擎对象
	用于保存db模块的核心函数:create_engine创建出来的数据库连接
	"""
	def __init__(self,connect):
		self._connect = connect
	def connect(self):
		return self._connect()


class _DbCtx(threading.local):
	"""
	db模块核心对象,数据库连接的上下文对象,负责从数据库获取和释放连接
	取得的连接是惰性连接对象,因此只有调用cursor对象时,才会真正获取数据库连接
	该对象是一个Threadlocal对象,因此绑定在此对象上的数据仅对本线程可见
	"""
	def __init__(self): 
		"""
		__init__两个下划线不是一个下划线_init_
		初始化连接的上下文对象,获得一个惰性连接
		"""
		logging.info('open lazy connection...')
		self.connection = None
		self.transactions = 0

	def is_init(self):
		return not self.connection is None

	def init(self):
		self.connection = _LasyConnection()
		self.transactions = 0

	def cleanup(self):
		self.connection.cleanup()
		self.connection = None

	def cursor(self):
		return self.connection.cursor()

_db_ctx = _DbCtx()

class _LasyConnection(object):
		"""
		惰性连接,获取游标时才连接数据库
		"""
		def __init__(self):
			self.connection = None

		def cursor(self):
				if self.connection is None:
					_connection = engine.connect()
					logging.info('[CONNECTION] [OPEN] connection <%s>...' % hex(id(_connection)))
					self.connection = _connection
				return self.connection.cursor()

		def commit(self):
			self.connection.commit()

		def rollback(self):
			self.connection.rollback()

		def cleanup(self):
			if self.connection:
				_connection = self.connection
				self.connection = None
				logging.info('[CONNECTION] [CLOSE] connection <%s>...' % hex(id(connection)))
				_connection.close()


class _ConnectionCtx(object):
	def __enter__(self):
		"""
		获取惰性连接对象
		"""
		global _db_ctx
		self.should_cleanup = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_cleanup = True
		return self
	
	def __exit__(self,exctype,excvalue,traceback):
		"""
		释放连接
		"""
		global _db_ctx
		if self.should_cleanup:
			_db_ctx.cleanup()

def connection():
	return _ConnectionCtx()

def with_connection(func):
	"""
	装饰器.装饰with语法
	"""
	@functools.wraps(func)
	def _wrapper(*args,**kw):
		with _ConnectionCtx():
			return func(*args,**kw)
	return _wrapper

def transaction():
	return _TransactionCtx()

def with_transaction(func):
	@functools.wraps(func)
	def _wrapper(*args,**kw):
		with _TransactionCtx():
			func(*args,**kw)
	return _wrapper

@with_connection
def _select(sql,first,*args):
	global _db_ctx
	cursor = None
	sql = sql.replace('?','%s')
	logging.info('SQL: %s, ARGS: %s' % (sql, args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql, args)
		if cursor.description:
			names = [x[0] for x in cursor.description]
		if first:
			values = cursor.fetchone()
			if not values:
				return None
			return Dict(names, values)
		return [Dict(names, x) for x in cursor.fetchall()]
	finally:
		if cursor:
			cursor.close()


def select_one(sql, *args):
	"""
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
	"""
	return _select(sql, True, *args)


def select_int(sql, *args):
	"""
	执行一个sql 返回一个数值，
	注意仅一个数值，如果返回多个数值将触发异常
	>>> u1 = dict(id=96900, name='Ada', email='ada@test.org', passwd='A-12345', last_modified=time.time())
	>>> u2 = dict(id=96901, name='Adam', email='adam@test.org', passwd='A-12345', last_modified=time.time())
	>>> insert('user', **u1)
	1
	>>> insert('user', **u2)
	1
	>>> select_int('select count(*) from user')
	5
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
	"""
	d = _select(sql, True, *args)
	if len(d) != 1:
		raise MultiColumnsError('Expect only one column.')
	return d.values()[0]


def select(sql, *args):
	"""
	执行sql 以列表形式返回结果
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
	"""
	return _select(sql, False, *args)


@with_connection
def _update(sql, *args):
	"""
	执行update 语句，返回update的行数
	"""
	global _db_ctx
	cursor = None
	sql = sql.replace('?', '%s')
	logging.info('SQL: %s, ARGS: %s' % (sql, args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql, args)
		r = cursor.rowcount
		if _db_ctx.transactions == 0:
			# no transaction enviroment:
			logging.info('auto commit')
			_db_ctx.connection.commit()
		return r
	finally:
		if cursor:
			cursor.close()


def update(sql, *args):
	"""
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
	>>> update('update user set passwd=? where id=?', '***', '123')
	0
	"""
	return _update(sql, *args)


def insert(table, **kw):
	"""
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
	"""
	cols, args = zip(*kw.iteritems())
	sql = 'insert into `%s` (%s) values (%s)' % (table, ','.join(['`%s`' % col for col in cols]), ','.join(['?' for i in range(len(cols))]))
	return _update(sql, *args)


class Dict(dict):
	"""
	字典对象
	实现一个简单的可以通过属性访问的字典，比如 x.key = value
	"""
	def __init__(self, names=(), values=(), **kw):
		super(Dict, self).__init__(**kw)
		for k, v in zip(names, values):
			self[k] = v

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

	def __setattr__(self, key, value):
		self[key] = value


class DBError(Exception):
	pass


class MultiColumnsError(DBError):
	pass

class _TransactionCtx(object):
	def _enter_(self):
		"""
		每遇到一层事务嵌套+1
		"""
		global _db_ctx
		self.should_close_conn = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_close_conn = True
		_db_ctx.transaction = _db_ctx.transacitons + 1
		logging.info('begin transaction...' if _db_ctx.transactions == 1 else 'join current transaction...')
		return self

	def _exit_(self,exctype,excvalue,traceback):
		"""
		离开一层事务嵌套-1,到0时离开
		"""
		global _db_ctx
		_db_ctx.transactions = _db_ctx.transactions - 1
		try:
			if _db_ctx.transactions == 0:
				if exctype is None:
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

