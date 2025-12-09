import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import json
import os
import asyncio
from typing import Optional, List
import aiohttp
import random
from collections import defaultdict
import pytz

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Файлы для хранения данных
RULES_FILE = 'server_rules.json'
WARNINGS_FILE = 'warnings.json'
LOG_CHANNEL_FILE = 'log_channel.json'
MOD_ROLES_FILE = 'mod_roles.json'

# Загрузка данных
def load_json(filename, default={}):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

rules_data = load_json(RULES_FILE, {'rules': {}, 'categories': []})
warnings_data = load_json(WARNINGS_FILE)
log_channels = load_json(LOG_CHANNEL_FILE)
mod_roles = load_json(MOD_ROLES_FILE, {'roles': []})

# ---------- 1. СИСТЕМА ПРЕДУПРЕЖДЕНИЙ (WARN SYSTEM) ----------
@bot.tree.command(name="варн", description="Выдать предупреждение участнику")
@app_commands.describe(
    участник="Участник, получающий предупреждение",
    причина="Причина предупреждения",
    уровень="Уровень серьезности (1-3)"
)
async def warn_member(
    interaction: discord.Interaction,
    участник: discord.Member,
    причина: str,
    уровень: int = 1
):
    """Выдать предупреждение участнику"""
    if not await check_mod_permissions(interaction):
        return
    
    user_id = str(участник.id)
    if user_id not in warnings_data:
        warnings_data[user_id] = []
    
    warning = {
        'id': len(warnings_data[user_id]) + 1,
        'moderator': interaction.user.name,
        'moderator_id': interaction.user.id,
        'reason': причина,
        'level': min(max(уровень, 1), 3),
        'timestamp': datetime.now().isoformat(),
        'active': True
    }
    
    warnings_data[user_id].append(warning)
    save_json(WARNINGS_FILE, warnings_data)
    
    # Автоматические действия по уровню
    actions = {
        1: "Первое предупреждение",
        2: "Второе предупреждение - временный мут",
        3: "Третье предупреждение - рассмотрение на бан"
    }
    
    # Отправляем логи
    await log_action(
        interaction.guild,
        "⚠️ ВЫДАЧА ВАРНА",
        f"**Модератор:** {interaction.user.mention}\n"
        f"**Участник:** {участник.mention}\n"
        f"**Причина:** {причина}\n"
        f"**Уровень:** {уровень}\n"
        f"**Действие:** {actions.get(уровень, 'Предупреждение')}"
    )
    
    embed = discord.Embed(
        title="⚠️ Предупреждение выдано",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Участник", value=участник.mention, inline=True)
    embed.add_field(name="Уровень", value=f"Уровень {уровень}", inline=True)
    embed.add_field(name="Причина", value=причина, inline=False)
    embed.add_field(name="Всего варнов", value=str(len(warnings_data[user_id])), inline=True)
    embed.set_footer(text=f"Модератор: {interaction.user.name}")
    
    await interaction.response.send_message(embed=embed)
    
    # Отправляем DM участнику
    try:
        dm_embed = discord.Embed(
            title="⚠️ Вы получили предупреждение",
            description=f"На сервере **{interaction.guild.name}**",
            color=discord.Color.orange()
        )
        dm_embed.add_field(name="Причина", value=причина, inline=False)
        dm_embed.add_field(name="Уровень", value=f"Уровень {уровень}", inline=True)
        dm_embed.add_field(name="Модератор", value=interaction.user.name, inline=True)
        dm_embed.set_footer(text="Пожалуйста, соблюдайте правила сервера")
        await участник.send(embed=dm_embed)
    except:
        pass
    
    # Автоматическое наказание при 3 предупреждениях
    active_warnings = [w for w in warnings_data[user_id] if w['active']]
    if len(active_warnings) >= 3:
        await apply_auto_punishment(участник, interaction.user)

@bot.tree.command(name="варны_посмотреть", description="Посмотреть предупреждения участника")
@app_commands.describe(участник="Участник для проверки")
async def view_warnings(interaction: discord.Interaction, участник: discord.Member):
    """Посмотреть предупреждения участника"""
    if not await check_mod_permissions(interaction):
        return
    
    user_id = str(участник.id)
    user_warnings = warnings_data.get(user_id, [])
    
    if not user_warnings:
        embed = discord.Embed(
            title="✅ Нет предупреждений",
            description=f"У {участник.mention} нет активных предупреждений",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    active_warnings = [w for w in user_warnings if w['active']]
    inactive_warnings = [w for w in user_warnings if not w['active']]
    
    embed = discord.Embed(
        title=f"📋 Предупреждения {участник.name}",
        description=f"Всего: {len(user_warnings)} | Активных: {len(active_warnings)}",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )
    
    if active_warnings:
        active_text = ""
        for warn in active_warnings[-5:]:  # Последние 5 предупреждений
            dt = datetime.fromisoformat(warn['timestamp'])
            active_text += (
                f"**#{warn['id']}** • Уровень {warn['level']}\n"
                f"Причина: {warn['reason']}\n"
                f"Модератор: {warn['moderator']} • {dt.strftime('%d.%m.%Y %H:%M')}\n\n"
            )
        embed.add_field(name="🟡 Активные предупреждения", value=active_text, inline=False)
    
    if inactive_warnings:
        embed.add_field(
            name="⚪ Снятые предупреждения",
            value=f"{len(inactive_warnings)} предупреждений снято",
            inline=False
        )
    
    embed.set_footer(text=f"ID: {участник.id}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="варн_снять", description="Снять предупреждение")
@app_commands.describe(
    участник="Участник",
    номер_варна="Номер предупреждения для снятия (или 'все')"
)
async def remove_warning(interaction: discord.Interaction, участник: discord.Member, номер_варна: str):
    """Снять предупреждение"""
    if not await check_mod_permissions(interaction):
        return
    
    user_id = str(участник.id)
    if user_id not in warnings_data or not warnings_data[user_id]:
        await interaction.response.send_message("❌ У участника нет предупреждений", ephemeral=True)
        return
    
    if номер_варна.lower() == 'все':
        for warn in warnings_data[user_id]:
            warn['active'] = False
        count = len(warnings_data[user_id])
        message = f"✅ Сняты все предупреждения ({count})"
    else:
        try:
            warn_id = int(номер_варна)
            for warn in warnings_data[user_id]:
                if warn['id'] == warn_id:
                    warn['active'] = False
                    message = f"✅ Предупреждение #{warn_id} снято"
                    break
            else:
                await interaction.response.send_message("❌ Предупреждение не найдено", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Неверный номер предупреждения", ephemeral=True)
            return
    
    save_json(WARNINGS_FILE, warnings_data)
    
    await log_action(
        interaction.guild,
        "✅ СНЯТИЕ ВАРНА",
        f"**Модератор:** {interaction.user.mention}\n"
        f"**Участник:** {участник.mention}\n"
        f"**Действие:** {message}"
    )
    
    await interaction.response.send_message(f"✅ {message} для {участник.mention}")

async def apply_auto_punishment(member: discord.Member, moderator: discord.User):
    """Автоматическое наказание при 3+ варнах"""
    try:
        # Временный мут на 24 часа
        mute_role = discord.utils.get(member.guild.roles, name="Muted")
        if not mute_role:
            # Создаем роль мута если её нет
            mute_role = await member.guild.create_role(
                name="Muted",
                color=discord.Color.dark_gray(),
                reason="Автоматическое создание роли для мута"
            )
            
            # Запрещаем права для всех каналов
            for channel in member.guild.channels:
                await channel.set_permissions(mute_role, send_messages=False)
        
        await member.add_roles(mute_role, reason="3 активных предупреждения")
        
        # Планируем автоматическое снятие мута
        await asyncio.sleep(24 * 3600)  # 24 часа
        await member.remove_roles(mute_role, reason="Автоматическое снятие мута")
        
    except Exception as e:
        print(f"Ошибка при автоматическом наказании: {e}")

# ---------- 2. СИСТЕМА ЛОГИРОВАНИЯ ----------
@bot.tree.command(name="логи_канал", description="Установить канал для логов")
@app_commands.describe(канал="Канал для логов")
async def set_log_channel(interaction: discord.Interaction, канал: discord.TextChannel):
    """Установить канал для логов"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Только администраторы могут настраивать логи", ephemeral=True)
        return
    
    log_channels[str(interaction.guild.id)] = канал.id
    save_json(LOG_CHANNEL_FILE, log_channels)
    
    embed = discord.Embed(
        title="✅ Канал логов установлен",
        description=f"Логи будут отправляться в {канал.mention}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

async def log_action(guild: discord.Guild, title: str, description: str):
    """Отправить лог в канал"""
    channel_id = log_channels.get(str(guild.id))
    if not channel_id:
        return
    
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blurple(),
        timestamp=datetime.now()
    )
    embed.set_footer(text=f"ID сервера: {guild.id}")
    
    try:
        await channel.send(embed=embed)
    except:
        pass

# ---------- 3. СИСТЕМА МОДЕРАТОРСКИХ РОЛЕЙ ----------
@bot.tree.command(name="мод_роль_добавить", description="Добавить роль модератора")
@app_commands.describe(роль="Роль модератора")
async def add_mod_role(interaction: discord.Interaction, роль: discord.Role):
    """Добавить роль модератора"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Только администраторы могут добавлять мод роли", ephemeral=True)
        return
    
    guild_id = str(interaction.guild.id)
    if guild_id not in mod_roles:
        mod_roles[guild_id] = {'roles': []}
    
    if роль.id not in mod_roles[guild_id]['roles']:
        mod_roles[guild_id]['roles'].append(роль.id)
        save_json(MOD_ROLES_FILE, mod_roles)
        await interaction.response.send_message(f"✅ Роль {роль.mention} добавлена как модераторская")
    else:
        await interaction.response.send_message("❌ Эта роль уже является модераторской", ephemeral=True)

async def check_mod_permissions(interaction: discord.Interaction) -> bool:
    """Проверка прав модератора"""
    if interaction.user.guild_permissions.administrator:
        return True
    
    guild_id = str(interaction.guild.id)
    if guild_id in mod_roles:
        for role_id in mod_roles[guild_id]['roles']:
            role = interaction.guild.get_role(role_id)
            if role and role in interaction.user.roles:
                return True
    
    await interaction.response.send_message(
        "❌ У вас недостаточно прав для выполнения этой команды",
        ephemeral=True
    )
    return False

# ---------- 4. СИСТЕМА АВТОМОДЕРАЦИИ ----------
@bot.event
async def on_message(message: discord.Message):
    """Автомодерация сообщений"""
    if message.author.bot:
        return
    
    # Проверка на спам
    if await check_spam(message):
        await message.delete()
        await message.channel.send(
            f"{message.author.mention}, пожалуйста, не спамьте!",
            delete_after=5
        )
        return
    
    # Проверка на плохие слова
    bad_words = await load_bad_words()
    if bad_words and await contains_bad_words(message.content, bad_words):
        await message.delete()
        await message.author.send(
            f"Ваше сообщение на сервере {message.guild.name} было удалено "
            f"из-за нарушения правил общения."
        )
        return
    
    await bot.process_commands(message)

async def check_spam(message: discord.Message) -> bool:
    """Проверка на спам"""
    # Простая проверка на повторяющиеся сообщения
    recent_messages = []
    async for msg in message.channel.history(limit=5):
        if msg.author == message.author and not msg.author.bot:
            recent_messages.append(msg.content)
    
    if len(recent_messages) >= 3 and all(msg == message.content for msg in recent_messages[-2:]):
        return True
    
    # Проверка на слишком много упоминаний
    if len(message.mentions) > 5:
        return True
    
    return False

async def load_bad_words():
    """Загрузка списка запрещенных слов"""
    try:
        with open('bad_words.txt', 'r', encoding='utf-8') as f:
            return [line.strip().lower() for line in f if line.strip()]
    except:
        return []

async def contains_bad_words(text: str, bad_words: list) -> bool:
    """Проверка на запрещенные слова"""
    text_lower = text.lower()
    for word in bad_words:
        if word in text_lower:
            return True
    return False

# ---------- 5. СИСТЕМА ТИКЕТОВ ----------
TICKET_CATEGORY_NAME = "🎫 ТИКЕТЫ"

@bot.tree.command(name="тикет", description="Создать тикет для обращения")
@app_commands.describe(тема="Тема тикета", описание="Подробное описание проблемы")
async def create_ticket(interaction: discord.Interaction, тема: str, описание: str):
    """Создание тикета"""
    # Ищем или создаем категорию для тикетов
    category = discord.utils.get(interaction.guild.categories, name=TICKET_CATEGORY_NAME)
    if not category:
        category = await interaction.guild.create_category_channel(TICKET_CATEGORY_NAME)
    
    # Создаем канал для тикета
    ticket_channel = await interaction.guild.create_text_channel(
        name=f"тикет-{interaction.user.name}",
        category=category,
        topic=f"Тикет от {interaction.user.name} | Тема: {тема}"
    )
    
    # Настраиваем права доступа
    await ticket_channel.set_permissions(interaction.guild.default_role, view_channel=False)
    await ticket_channel.set_permissions(interaction.user, view_channel=True, send_messages=True)
    
    # Добавляем права для модераторов
    guild_id = str(interaction.guild.id)
    if guild_id in mod_roles:
        for role_id in mod_roles[guild_id]['roles']:
            role = interaction.guild.get_role(role_id)
            if role:
                await ticket_channel.set_permissions(role, view_channel=True, send_messages=True)
    
    # Создаем сообщение в тикете
    embed = discord.Embed(
        title=f"🎫 Тикет: {тема}",
        description=описание,
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Автор", value=interaction.user.mention, inline=True)
    embed.add_field(name="Статус", value="🔓 Открыт", inline=True)
    embed.set_footer(text=f"ID тикета: {ticket_channel.id}")
    
    await ticket_channel.send(f"{interaction.user.mention}", embed=embed)
    
    # Кнопки для управления тикетом
    view = TicketView()
    await ticket_channel.send("Управление тикетом:", view=view)
    
    await interaction.response.send_message(
        f"✅ Тикет создан: {ticket_channel.mention}",
        ephemeral=True
    )

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.red)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await check_mod_permissions(interaction):
            await interaction.channel.delete()
    
    @discord.ui.button(label="📋 Добавить участника", style=discord.ButtonStyle.green)
    async def add_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await check_mod_permissions(interaction):
            # Здесь можно реализовать добавление участника
            await interaction.response.send_message("Функция в разработке", ephemeral=True)

# ---------- 6. СИСТЕМА СТАТИСТИКИ ----------
@bot.tree.command(name="статистика", description="Статистика сервера и бота")
async def server_stats(interaction: discord.Interaction):
    """Статистика сервера"""
    guild = interaction.guild
    
    # Статистика участников
    total_members = guild.member_count
    online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
    bot_count = sum(1 for m in guild.members if m.bot)
    
    # Статистика каналов
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    
    # Статистика правил
    total_rules = len(rules_data['rules'])
    total_categories = len(rules_data['categories'])
    
    # Статистика предупреждений
    total_warnings = sum(len(warns) for warns in warnings_data.values())
    active_warnings = sum(
        1 for warns in warnings_data.values() 
        for w in warns if w.get('active', False)
    )
    
    embed = discord.Embed(
        title="📊 СТАТИСТИКА СЕРВЕРА",
        color=discord.Color.purple(),
        timestamp=datetime.now()
    )
    
    embed.add_field(name="👥 Участники", 
                   value=f"Всего: {total_members}\nОнлайн: {online_members}\nБоты: {bot_count}", 
                   inline=True)
    
    embed.add_field(name="📁 Каналы", 
                   value=f"Текстовые: {text_channels}\nГолосовые: {voice_channels}\nКатегории: {categories}", 
                   inline=True)
    
    embed.add_field(name="📜 Правила", 
                   value=f"Всего правил: {total_rules}\nКатегорий: {total_categories}", 
                   inline=True)
    
    embed.add_field(name="⚠️ Предупреждения", 
                   value=f"Всего: {total_warnings}\nАктивных: {active_warnings}", 
                   inline=True)
    
    embed.add_field(name="📅 Создание сервера", 
                   value=guild.created_at.strftime("%d.%m.%Y"), 
                   inline=True)
    
    embed.add_field(name="👑 Владелец", 
                   value=guild.owner.mention, 
                   inline=True)
    
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.set_footer(text=f"ID сервера: {guild.id}")
    
    await interaction.response.send_message(embed=embed)

# ---------- 7. АВТОМАТИЧЕСКИЕ НАПОМИНАНИЯ ----------
@tasks.loop(hours=24)
async def daily_rules_reminder():
    """Ежедневное напоминание о правилах"""
    for guild in bot.guilds:
        rules_channel = discord.utils.get(guild.text_channels, name="правила")
        if rules_channel:
            embed = discord.Embed(
                title="📢 Ежедневное напоминание",
                description="Не забывайте соблюдать правила сервера!",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="Основные правила:",
                value="• Будьте уважительны\n• Не спамьте\n• Соблюдайте тематику каналов",
                inline=False
            )
            embed.set_footer(text="Приятного общения!")
            
            try:
                await rules_channel.send(embed=embed)
            except:
                pass

# ---------- 8. СИСТЕМА ВЕРИФИКАЦИИ ----------
VERIFICATION_ROLE_NAME = "✅ Проверенный"

@bot.tree.command(name="верификация", description="Настроить систему верификации")
@app_commands.describe(канал="Канал для верификации", роль="Роль после верификации")
async def setup_verification(interaction: discord.Interaction, канал: discord.TextChannel, роль: discord.Role):
    """Настройка системы верификации"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Только администраторы могут настраивать верификацию", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="✅ ВЕРИФИКАЦИЯ",
        description=(
            "Нажмите кнопку ниже для прохождения верификации\n\n"
            "После нажатия вы получите доступ к серверу"
        ),
        color=discord.Color.green()
    )
    
    view = VerificationView(роль)
    await канал.send(embed=embed, view=view)
    
    await interaction.response.send_message(f"✅ Система верификации настроена в {канал.mention}", ephemeral=True)

class VerificationView(discord.ui.View):
    def __init__(self, role: discord.Role):
        super().__init__(timeout=None)
        self.role = role
    
    @discord.ui.button(label="✅ Пройти верификацию", style=discord.ButtonStyle.green)
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.role not in interaction.user.roles:
            await interaction.user.add_roles(self.role)
            embed = discord.Embed(
                title="✅ Верификация пройдена!",
                description=f"Добро пожаловать на сервер, {interaction.user.mention}!",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Вы уже верифицированы!", ephemeral=True)

# ---------- 9. КОМАНДА ПОМОЩИ С ПАГИНАЦИЕЙ ----------
@bot.tree.command(name="помощь", description="Показать все команды бота")
async def help_command(interaction: discord.Interaction):
    """Команда помощи с пагинацией"""
    pages = []
    
    # Страница 1: Основные команды
    embed1 = discord.Embed(
        title="📚 ПОМОЩЬ ПО КОМАНДАМ",
        description="Страница 1/3 - Основные команды",
        color=discord.Color.blue()
    )
    embed1.add_field(
        name="📜 Работа с правилами",
        value=(
            "`/правило_добавить` - Добавить правило\n"
            "`/правило_найти` - Найти правило\n"
            "`/правила_список` - Список категорий\n"
            "`/правила_обновить` - Обновить канал правил"
        ),
        inline=False
    )
    pages.append(embed1)
    
    # Страница 2: Модерация
    embed2 = discord.Embed(
        title="📚 ПОМОЩЬ ПО КОМАНДАМ",
        description="Страница 2/3 - Модерация",
        color=discord.Color.blue()
    )
    embed2.add_field(
        name="⚖️ Модерация",
        value=(
            "`/варн` - Выдать предупреждение\n"
            "`/варны_посмотреть` - Посмотреть варны\n"
            "`/варн_снять` - Снять варн\n"
            "`/мод_роль_добавить` - Добавить мод роль"
        ),
        inline=False
    )
    pages.append(embed2)
    
    # Страница 3: Утилиты
    embed3 = discord.Embed(
        title="📚 ПОМОЩЬ ПО КОМАНДАМ",
        description="Страница 3/3 - Утилиты",
        color=discord.Color.blue()
    )
    embed3.add_field(
        name="🛠️ Утилиты",
        value=(
            "`/тикет` - Создать тикет\n"
            "`/статистика` - Статистика сервера\n"
            "`/логи_канал` - Настроить логи\n"
            "`/верификация` - Настроить верификацию"
        ),
        inline=False
    )
    pages.append(embed3)
    
    # Отправляем первую страницу с кнопками
    view = PaginationView(pages, timeout=60)
    await interaction.response.send_message(embed=pages[0], view=view)

class PaginationView(discord.ui.View):
    def __init__(self, pages, timeout=60):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
    
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.gray)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.pages[self.current_page])
    
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.pages[self.current_page])
    
    @discord.ui.button(label="❌", style=discord.ButtonStyle.red)
    async def close_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

# ---------- 10. BACKUP И ВОССТАНОВЛЕНИЕ ----------
@bot.tree.command(name="бэкап", description="Создать резервную копию правил")
async def backup_rules(interaction: discord.Interaction):
    """Создание бэкапа правил"""
    if not await check_mod_permissions(interaction):
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_rules_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(rules_data, f, ensure_ascii=False, indent=2)
    
    await interaction.response.send_message(
        f"✅ Бэкап создан: `{filename}`",
        file=discord.File(filename)
    )
    
    # Удаляем временный файл
    os.remove(filename)

# ---------- ОБНОВЛЕННЫЙ ON_READY ----------
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} успешно запущен!')
    print(f'🆔 ID бота: {bot.user.id}')
    print(f'📊 Серверов: {len(bot.guilds)}')
    
    # Запускаем фоновые задачи
    daily_rules_reminder.start()
    
    try:
        synced = await bot.tree.sync()
        print(f'✅ Синхронизировано {len(synced)} команд')
    except Exception as e:
        print(f'❌ Ошибка синхронизации: {e}')
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"правила на {len(bot.guilds)} серверах"
        ),
        status=discord.Status.online
    )

# ---------- ЗАПУСК БОТА ----------
if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        try:
            with open('token.txt', 'r') as f:
                TOKEN = f.read().strip()
        except:
            print("❌ Токен не найден! Создайте файл token.txt")
            exit(1)
    
    print("🚀 Запуск расширенного бота...")
    bot.run(TOKEN)