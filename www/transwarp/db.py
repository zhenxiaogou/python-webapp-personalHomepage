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

#global engine object:
engine = None

def create_engine(user,password,database,host,port,**kw):
	"""
	db模型的核心函数,用于连接数据库,生成全局对象engine
	engine对象持有数据库连接
	"""
	import MySQLdb
	golbal engine
	if engine is not None:
		raise DBError('Engine si already initialized.')
	params = dict(user = user,password = password,database = database,host = host,port = port)
	defaults = dict(use_unicode = True,charset = 'utf8',collation='utf8_general_ci',autocommit=False)
	for k,v in defaults.iteritems
		params[k] = kw.pop(k,v)
	params.update(kw)
	params['buffered'] = True
	engine = _Engine(lambda:MySQLdb.connect(**params))
	logging.info('Init mysql engine <%s> ok.' % hex(id(engine)))

class _Engine(object):
	"""
	数据库引擎对象
	用于保存db模块的核心函数:create_engine创建出来的数据库连接
	"""
	def _init_(self,connect):
		self._connect = connect
	def connect(self):
		return self._connect()


class _DBCtx(threading.local):
	def _init_(self):
		self.connection = None
		self.transactions = 0

	def is_init(self):
		return not self.connection is None

	def init(self):
		self.connection = _lasyConnection()
		self.transactions = 0

	def cleanup(self):
		self.connection.cleanup()
		self.connection = None

	def cursor(self):
		return self.connection.cursor()

_db_ctx = _DbCtx()

class _ConnectionCtx(object):
	def _enter_(self):
		global _db_ctx
		self.should_cleanup = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_cleanup = True
		return self
	def _exit_(self,exctype,excvalue,traceback):
		global _db_ctx
		if self.should_cleanup:
			_db_ctx.cleanup()

def connection():
	return _ConnectionCtx()

@with_connection
def select(sql,*args):
	pass

@with_connection
def update(sql,*args):
	pass

@with_transaction
def do_in_transaction():
	pass

class _TransactionCtx(object):
	def _enter_(self):
		global _db_ctx
		self.should_close_conn = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_close_conn = True
		_db_ctx.transaction = _db_ctx.transacitons + 1
		return self

	def _exit(self,exctype,excvalue,traceback):
		global _db_ctx
		_db_ctx.transactions = _db_ctx.transactions - 1
		try:
			if _db_ctx.transactions = 0
				if exctype is None:
					self.commit()
				else:
					self.rollback()
		finally:
			if self.should_close_conn:
				_db_ctx.cleanup()

	def commit(self):
		global _db_ctx
		try:
			_db_ctx.connection.commit()
		except:
			_db_ctx.connection.rollback()
			raise

	def rollback(self):
		global _db_ctx
		_db_ctx.connection.rollback()

