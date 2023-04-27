import json
from datetime import datetime, timezone
from typing import Dict, List
#
import urllib.request
#
import telepot
import typing
from paho.mqtt.client import MQTTMessage
from telepot.loop import MessageLoop

from core.device.model.DeviceAbility import DeviceAbility
from .model.TelegramUser import TelegramUser
from core.ProjectAliceExceptions import SkillStartingFailed
from core.base.model.AliceSkill import AliceSkill
from core.base.model.Intent import Intent
from core.commons import constants
from core.dialog.model.DialogSession import DialogSession
from core.util.Decorators import MqttHandler

#
proxy_url = 'http://SEU_PROXY_AQUI:PORTA_DO_PROXY_AQUI'
telepot.api.set_proxy(proxy_url, ('USER_DO_PROXY_AQUI', 'SENHA_DO_PROXY_AQUI'))
#

class Telegram(AliceSkill):
	"""
	Author: Psychokiller1888
	Description: Chat with Alice directly from your mobile device with the `privacy first` app Telegram
	"""

	DATABASE = {
		'users': [
			'id integer PRIMARY KEY',
			'userId INTEGER NOT NULL',
			'userName TEXT NOT NULL',
			'userLastName TEXT',
			'accessLevel TEXT DEFAULT user',
			'blacklisted INTEGER DEFAULT 0'
		]
	}

	_INTENT_ANSWER_YES_OR_NO = Intent('AnswerYesOrNo')

	def __init__(self):

		self._INTENTS = [
			self._INTENT_ANSWER_YES_OR_NO
		]

		self._bot = None
		self._me = None
		self._loop = None
		self._chats: List = list()
		self._users = dict()
		self._usersToSessions: Dict = dict()

		self._INTENT_ANSWER_YES_OR_NO.dialogMapping = {
			'askingToAddNewTelegramUser': self.answerYesOrNo
		}

		super().__init__(self._INTENTS, self.DATABASE)


	def onStart(self):
		super().onStart()

		if not self.getConfig('token'):
			raise SkillStartingFailed(skillName=self._name, error='Please provide your bot token in the skill settings')

		self._bot = telepot.Bot(self.getConfig('token'))

		try:
			self._me = self._bot.getMe()

		except:
			raise SkillStartingFailed(skillName=self._name, error='Your token seems incorrect')

		self.loadUsers()
		self.logInfo(f'Loaded {len(self._users)} user', plural='users')


	def loadUsers(self):
		users = self.databaseFetch(tableName='users', query='SELECT * FROM :__table__')
		self._users = {user['userId']: user for user in users if users}


	def onBooted(self) -> bool:
		if not self._bot:
			return False

		self._loop = MessageLoop(self._bot, self.incomingMessage).run_as_thread()
		return super().onBooted()


	def onStop(self):
		super().onStop()
		if not self._bot:
			return

		try:
			# noinspection PyProtectedMember
			self._bot._scheduler.join(timeout=1)
		except:
			pass  # The bot's thread needs to be stopped if the skill is reloaded, not when Alice goes down


	def answerYesOrNo(self, session: DialogSession):
		if self.Commons.isYes(session):
			self.endDialog(
				sessionId=session.sessionId,
				text=self.randomTalk(text='okAdded')
			)
			self.databaseInsert(
				tableName='users',
				values={
					'userId': session.customData['userId'],
					'userName': session.customData['fromName'],
					'userLastName': session.customData['fromLastName'],
					'blacklisted': 0
				}
			)
			setting = self.getConfig('whitelist')
			if setting:
				self.updateConfig('whitelist', f'{setting},{session.customData["fromName"]}/{session.customData["userId"]}')
			else:
				self.updateConfig('whitelist', f'{session.customData["fromName"]}/{session.customData["userId"]}')

			self.loadUsers()
			self.sendMessage(chatId=session.customData['userId'], message=self.randomTalk(text='whitelisted', replace=[session.customData['fromName']]))
		else:
			self.endDialog(
				sessionId=session.sessionId,
				text=self.randomTalk(text='okNotAdded')
			)
			self.databaseInsert(
				tableName='users',
				values={
					'userId': session.customData['userId'],
					'userName': session.customData['fromName'],
					'userLastName': session.customData['fromLastName'],
					'blacklisted': 1
				}
			)
			setting = self.getConfig('blacklist')
			if setting:
				self.updateConfig('blacklist', f'{setting},{session.customData["fromName"]}/{session.customData["userId"]}')
			else:
				self.updateConfig('blacklist', f'{session.customData["fromName"]}/{session.customData["userId"]}')

			self.loadUsers()
			self.sendMessage(chatId=session.customData['userId'], message=self.randomTalk(text='blacklisted', replace=[session.customData['fromName']]))


	def incomingMessage(self, message: dict):
		self.logDebug(f'Incoming message: {message}')

		try:
			chatId = message['chat']['id']
			fromName = message['from']['first_name']
			date = message['date']
			fromLastName = message['from'].get('last_name', '')
		except KeyError:
			self.logWarning('Invalid message format')
			return

		# Drop too old messages in case Alice was offline
		timestamp = int(datetime.now(timezone.utc).timestamp())
		if date <= timestamp - 5:
			self.logInfo(f'Dropped old message from {fromName}: {message["text"]}')
			return

		# noinspection SqlResolve
		user = self.databaseFetch(tableName='users', query='SELECT * FROM :__table__ WHERE userId = :userId', values={'userId': chatId})
		if not user:
			self.logWarning(f'An unknown user texted me! His name and id: {fromName}/{chatId}')
			if not self.getAliceConfig('disableSound') and not self.getAliceConfig('disableCapture'):
				deviceUid = self.DeviceManager.getMainDevice().uid
			else:
				device = self.DeviceManager.getDevicesWithAbilities(abilities=[DeviceAbility.NOTIFY])
				if not device:
					self.logInfo('Cannot ask for user addition, no device found to do so')
					return
				deviceUid = device[-1].uid

			self.ask(
				deviceUid=deviceUid,
				text=self.randomTalk(text='unknownUser', replace=[fromName]),
				intentFilter=[self._INTENT_ANSWER_YES_OR_NO],
				currentDialogState='askingToAddNewTelegramUser',
				customData={
					'userId'      : chatId,
					'fromName'    : fromName,
					'fromLastName': fromLastName
				}
			)
			return

		if user[0]['blacklisted'] == 1:
			self.logWarning(f'Blacklisted user texting: {fromName}/{chatId}')
			return

		deviceUid = str(chatId)

		# Let's make a couple of funny things :)
		if message['text'] == '❤':
			self.sendMessage(chatId, '❤❤ you too!')
		elif message['text'] == '😍':
			self.sendMessage(chatId, '😘')
		elif message['text'] == '😘':
			self.sendMessage(chatId, '😍')
		elif message['text'] in self.LanguageManager.getStrings('greetingForms', skill=self.name):
			self.sendMessage(chatId, self.randomTalk(text='greet', replace=[fromName]))
		else:
			self._chats.append(deviceUid)

			if fromName in self._usersToSessions:
				session = self.DialogManager.getSession(sessionId=self._usersToSessions[fromName])
			else:
				session = self.DialogManager.newSession(deviceUid=deviceUid, user=fromName, increaseTimeout=10)

			session.textOnly = True

			mqttMessage = MQTTMessage()
			mqttMessage.payload = json.dumps({'sessionId': session.sessionId, 'siteId': deviceUid, 'text': message['text']})
			session.extend(message=mqttMessage)
			self._usersToSessions[fromName] = session.sessionId

			self.MqttManager.publish(topic=constants.TOPIC_NLU_QUERY, payload={
				'input'    : message['text'],
				'sessionId': session.sessionId
			})


	def onContinueSession(self, session: DialogSession):
		if session.deviceUid not in self._chats:
			return

		if session.payload.get('text', None):
			self.sendMessage(session.deviceUid, session.payload['text'])


	def onEndSession(self, session: DialogSession, reason: str = 'nominal'):
		if session.deviceUid not in self._chats:
			return
		self._chats.remove(session.deviceUid)

		if reason == 'timeout':
			self.sendMessage(session.deviceUid, self.randomTalk(text='sessionTimeout'))
		elif reason != 'nominal':
			self.sendMessage(session.deviceUid, self.randomTalk(text='error', skill='system'))
		else:
			if session.payload.get('text', None):
				self.sendMessage(session.deviceUid, session.payload['text'])

		self._usersToSessions.pop(session.user, None)

	def sendMessage(self, chatId: str, message: str):
		if not self._bot and not self._me:
			self._bot = self._bot = telepot.Bot(self.getConfig('token'))
			self._me = self._bot.getMe()
		self._bot.sendMessage(chat_id=chatId, text=message)


	def refreshDatabase(self, _value: typing.Any) -> bool:
		try:
			# Only triggered by config update!!
			whitelisted = self.getConfig('whitelist')
			blacklisted = self.getConfig('blacklist')
			whitelist = self.createUserList(whitelisted, False)
			blacklist = self.createUserList(blacklisted, False)
			users: Dict[int, TelegramUser] = {**blacklist, **whitelist}

			# Check if what we have in config is what we have in db
			# First, did we add a new user into one of the lists?
			for userid, user in users.items():
				# noinspection SqlResolve
				if not self.databaseFetch(tableName='users', query='SELECT * FROM :__table__ WHERE userId = :userId', values={'userId': userid}):
					# We have a missing user, config was manually changed
					self.databaseInsert(
						tableName='users',
						values={
							'userId'      : userid,
							'userName'    : user.username,
							'userLastName': '',
							'blacklisted' : user.banned
						}
					)

			# Or did we remove one?
			for user in self.databaseFetch(tableName='users', query='SELECT * FROM :__table__'):
				if (user['blacklisted'] == 1 and user['userId'] not in blacklist) or (user['blacklisted'] == 0 and user['userId'] not in whitelist):
					# We have a removed user, config was manually changed
					self.DatabaseManager.delete(
						tableName='users',
						callerName=self.name,
						values={
							'userId': user['userId']
						}
					)
		except Exception as e:
			self.logDebug(f'Error refreshing database: {e}')
			return False

		return True


	def createUserList(self, baseString: str, isBlacklist: bool) -> dict:
		users: Dict[int, TelegramUser] = dict()
		if not baseString:
			return users

		for data in baseString.split(','):
			try:
				username = data.split('/')[0]
				userid = int(data.split('/')[1])
			except:
				self.logWarning(f'Wrong list format: {data}')
				continue

			users[userid] = TelegramUser(username, userid, 1 if isBlacklist else 0)

		return users


	# Telegram Node capture
	@MqttHandler('projectalice/nodered/telegramNotify')
	def telegramMessage(self, session: DialogSession):

		message = session.payload['message']['text']
		chatID = session.payload['chatID']

		defaultChatID = ''
		for key in self._users.keys():
			if not defaultChatID:
				defaultChatID = key

		if not chatID:
			chatID = defaultChatID
		if not message:
			message = 'No message was provided'

		self.sendMessage(chatId=chatID, message=str(message))
		self.endSession(
			sessionId=session.sessionId
		)

	def onSessionTimeout(self, session):
		"""
		if session times out, cleanout the relevant usersToSession
		"""
		super().onSessionTimeout(session)
		if session.deviceUid not in self._chats:
			return
		self._chats.remove(session.deviceUid)

		if session.user in self._usersToSessions:
			self.sendMessage(session.deviceUid, self.randomTalk(text='sessionTimeout'))
			self._usersToSessions.pop(session.user, None)
