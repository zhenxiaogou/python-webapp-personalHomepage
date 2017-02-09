#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
orm模块设计原因:
	1.简化操作
		sql操作的数据是 关系型数据,而python操作的是对象,为了简化编程需要对他们进行映射
		映射关系:
			表 ==> 行
			行 ==> 实例

设计orm接口:
	1.设计原则
		根据上层调用者设计简单易用的api接口
	2.设计调用接口
		1.表 <==> 类
			通过类的属性 来映射表的属性(表名,字段名,字段属性)
				from transwarp.orm import Model,StringField,IntegerField

				class ClassName(object):
					__table__ = 'users'
					id = IntegerField(primary_key=True)
					name = StringField()
			从中可以看出__table__拥有映射表名,id/name用于映射 字段对象(字段名和字段属性)
		2.行 <==> 实例
			通过实例的属性来映射行的值
				#创建实例
				user = User(id = 123,name = 'Michael')
				#存入数据库
				user.insert()
			最后 id/name 要变成user实例的属性
"""

import db
import logging

_triggers = frozenset(['pre_insert','pre_updata','pre_delete'])

class Model(dict):
	"""
	这是一个基类,用户在子类中定义映射关系,因此我们需要动态扫描子类属性
	从中抽取出类属性,完成类 <==> 表的映射, 这里需要用 metaclass 来实现
	最后将扫描的结果保存在类属性

		"__table__":表名
		"__mappings__":字段对象(字段的所有属性,见Field类)
		"__primary_key__":主键字段
		"__sql__":创建表时执行的sql

	子类在实例化时需要完成 实例属性 <==>行值 的映射,这里使用 定制dict 来实现.
		model 从字典继承而来,而且通过"__getattr__","__setattr__"将Model重写,
		使得其像javaspript的object对象那样,可以通过属性访问 比如a.key = value
	"""
	__metaclass__ = ModelMetaclass

	def __init__(self,**kw):
		super(Model,self).__init__(**kw)

	def __getattr__(self,key):
		"""
		get时生效,比如a[key],a.get(key)
		get时 返回属性的值
		"""
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"Dict object has no attribute `%s`" % key)

	def __setattr__(self,key,value):
		"""
		set时生效,比如a[key] = value,a = {'key1':value,'key2':value}
		set时添加属性
		"""
		self[key] = value

	@classmethod
	def get(cls,pk):
		d = db.select_one('select * from %s where %s=?' % (cls.__table__,cls.__primary_key__.name),pk)
		return cls(**d) if d else None

	@classmethod
	def find_first(cls,where,*args):
		d = db.select_one('select * from %s %s' % (cls.__table__,where),*args)
		return cls(**d) if d else None

	@classmethod
	def find_all(cls,*args):
		"""
		查询所有字段,将结果以一个列表返回
		"""
		L = db.select('select * from `%s`' % cls.__table__)
		return [cls(**d) for d in L]

	@classmethod
	def find_by(cls,where,*args):
		"""
		通过where语法进行查询 结果以列表形式返回
		"""
		L = db.select('select *from `%s` %s' % (cls.__table__,where),*args)
		return [cls(**d) for d in L]

	@classmethod
	def count_all(cls):
		"""
		执行select count(pk) from table,返回一个数值
		"""
		return db.select('select count(`%s`) from `%s`' % (cls.__primary_key__.name,cls.__table__))

	@classmethod
	def count_by(cls,where,*args):
		"""
		通过select count(pk) from table where...进行查询,返回一个数值
		"""
		return db.select_int('select count(`%s`) from `%s` %s' % (cls.__primary_key__.name,cls.__table__,where),*args)

	def updata(self):
		self.pre_updata and self.pre_updata()
		L = []
		args = []
		for k,v in self.__mappings__.iteritems():
			if v.updatable:
				if hasattr(self,k):
					arg = getattr(self,k)
				else:
					arg = v.default
					setattr(self,k,arg)
				L = append('`%s`=?' % k)
				args.append(arg)
		pk = self.__primary_key__.name
		args.append(getattr(self,pk))
		db.updata('updata `%s` set %s where %s = ?' % (self.__table__,','.join(L),pk), *args)
		return self

	def delete(self):
		"""
		通过db对象的updata接口 执行sql
			sql:delete from `user` where `id` = %s,ARGS:(10190,)
		"""
		self.pre_delete and self.pre_delete()
		pk = self.__primary_key__.name
		args = (getattr(self,pk),)
		db.updata('delete from `%s` where `%s`=?' % (self.__table__,pk),*args)
		return self

	def insert(self):
		"""
		"""
		self.pre_insert and self.pre_insert()
		params = {}
		for k,v in self.__mappings__.iteritems():
			if v.insertable:
				if not hasattr(self,k):
					setattr(self,k,v.default)
				params[v.name] = getattr(self,k)
		db.insert('%s' % self.__table__,**params)
		return self

class ModelMetaclass(type):
	"""
	对类对象动态完成以下操作
	避免修改model类:
		1.排除对model类的修改
	属性与字段的mapping:
		1.从类的属性字典中提出 类属性和字段类 的mapping
		2.提取完成后移除这些类属性,避免和实例属性冲突
		3.新增"__mappings__"属性,保存提取出的mapping数据
	类和表的mapping:
		1.提取类名,保存为表名,完成简单的类和表映射
		2.新增"__table__"属性,保存提取出的表名
	"""
	def __new__(cls,name,bases,attrs):
		if name == 'Model':
			return type.__new__(cls,name,bases,attrs)

		if not hasattr(cls,'subclasses'):
			cls.subclasses = {}
		if not name in cls.subclasses:
			cls.subclasses[name] = name
		else:
			logging.warning('Redefine class: %s' % name)

		logging.info('Scan ORMapping %s...' % name)
		mappings = dict()
		primary_key = None
		for k,v in attrs.iteritems():
			if isinstance(v,Field):
				if not v.name:
					v.name = k
				logging.info('[MAPPING] Found mapping: %s => %s' % (k,v))
				if v.primary_key:
					if primary_key:
						raise TypeError('Cannot define more than 1 primary key in class: %s' % name)
					if v.updatable:
						logging.warning('NOTE:change primary key to non-nullable.')
						v.nullable = False
					primary_key = v
				mapping[k] = v
		if not primary_key:
			raise TypeError('Primary key not defined in class: %s' % name)
		for k in mappings.iterkeys():
			attrs.pop(k)
		if not '__table__' in attrs:
			attrs['__table__'] = name.lower()
		attrs['__mappings__'] = mappings
		attrs['__primary_key__'] = primary_key
		attrs['__sql__'] = lambda self:_gen_sql(attrs['__table__'],mappings)
		for trigger in _triggers:
			if not trigger in attrs:
				attrs[trigger] = None
		return type.__new__(cls,name,bases,attrs)

class Field(object):
	"""
	保存数据库中表的 字段属性

	_count:类属性,每实例化一次该值+1
	self._order:实例属性,实例化时从类属性处得到,用于记录该实例的第多少个实例
	self._defalt:用于让orm自己填入缺省值,缺省值可以可调用对象,比如函数
	其他实例属性都是用于描述字段属性
	"""
	_count = 0

	def __init__(self,**kw):
		self.name = kw.get('name',None)
		self._default = kw.get('_default')
		self.primary_key = kw.get('primary_key',False)
		self.nullable = kw.get('nullable',False)
		self.updatable = kw.get('updatable',True)
		self.insertable = kw.get('insertable',True)
		self.ddl = kw.get('ddl','')
		self._order = Field._count
		Field._count += 1

	@property
	def default(self):
		"""
		利用getter实现的一个写保护的实例属性
		"""
		d = self._default
		return d() if callable(d) else d

	def __str(self):
		"""
		返回实例对象的描述信息,比如:
			<IntegerField:id,bigint,default(0),UI>
			类:实例:实例ddl属性:实例default信息,3中标志位:N U I
		"""
		s = ['<%s:%s,%s,default(%s),' % (self.__class__.__name__,self.name,self.ddl,self._default)]
		self.nullable and s.append('N')
		self.updatable and s.append('U')
		self.insertable and s.append('I')
		s.append('>')
		return ''.join(s)

class StringField(Field):
	"""
	保存String类型字段的属性
	"""
	def __init__(self, **kw):
		if 'default' not in kw:
			kw['default'] = ''
		if 'ddl' not in kw:
			kw['ddl'] not in kw:
			kw['ddl'] = 'varchar(255)'
		super(StringField, self).__init__(**kw)

class IntegerField(Field):
	"""
	保存int类型字段属性
	"""
	def __init__(self, **kw):
		if 'default' not in kw:
			kw['default'] = ''
		if 'ddl' not in kw:
			kw['ddl'] not in kw:
			kw['ddl'] = 'bigint'
		super(IntegerField, self).__init__(**kw)

class FloatField(Field):
	"""
	保存Float类型字段的属性
	"""
	def __init__(self, **kw):
		if 'default' not in kw:
			kw['default'] = 0.0
		if 'ddl' not in kw:
			kw['ddl'] = 'real'
		super(FloatField, self).__init__(**kw)

class BooleanField(Field):
	"""保存bool型字段的属性"""
	def __init__(self, **kw):
		if 'default' not in kw:
			kw['default'] = 0.0
		if 'ddl' not in kw:
			kw['ddl'] = 'bool'
		super(BooleanField, self).__init__(**kw)
		
class TextField(Field):
	"""
	保存text类型字段的属性
	"""
	def __init__(self, **kw):
		if 'default' not in kw:
			kw['default'] = 0.0
		if 'ddl' not in kw:
			kw['ddl'] = 'text'
		super(TextField, self).__init__(**kw)

class BlobField(Field):
	"""
	保存Blob类型字段的属性
	"""
	def __init__(self, **kw):
		if 'default' not in kw:
			kw['default'] = 0.0
		if 'ddl' not in kw:
			kw['ddl'] = 'blob'
		super(BlobField, self).__init__(**kw)

class VersionField(Field):
	"""
	保存Version类型字段的属性
	"""
	def __init__(self, name = None):
		super(VersionField, self).__init__(name = name,default = 0,ddl = 'bigint')


def _gen_sql(table_name, mappings):
	"""
	类 ==> 表时 生成创建表的sql
	"""
	pk = None
	sql = ['-- generating SQL for %s:' % table_name, 'create table `%s` (' % table_name]
	for f in sorted(mappings.values(), lambda x, y: cmp(x._order, y._order)):
		if not hasattr(f, 'ddl'):
			raise StandardError('no ddl in field "%s".' % f)
		ddl = f.ddl
		nullable = f.nullable
		if f.primary_key:
			pk = f.name
		#sql.append(nullable and '  `%s` %s,' % (f.name, ddl) or '  `%s` %s not null,' % (f.name, ddl))
		sql.append('  `%s` %s,' % (f.name, ddl) if nullable else '  `%s` %s not null,' % (f.name, ddl))
	sql.append('  primary key(`%s`)' % pk)
	sql.append(');')
	return '\n'.join(sql)



		
		
		
		
		
		

	

		

		
 