import asyncio, json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands

GUILD_ID=1323454227816906802
CHANNEL_ID=1534917454977962076
LEAGUE_ROLE_ID=1450893024379797514
MAX_PACKS,MIN_MEMBERS,MAX_MEMBERS=3,6,10
TZ=ZoneInfo('Europe/Berlin')
COLOR=0x3F3A78
FOOTER='Silent Concierge by Myxa | Ліга гільдій'
DATA=Path('data/guild_league.json')
ROLES={'tank':('🛡️','Tank'),'dps':('⚔️','DPS'),'shai':('🧪','Shai')}
PANEL=(
'## 🏆 Ліга гільдій\n'
'**Запис:** 1. обери `Tank / DPS / Shai`  2. **Записатися**  3. обери пачку.\n'
'**PL:** **Створити пачку** → день → час. Заявки: **PL: керування пачкою**.\n'
'*Мінімум для гри: 6 людей. Максимум: 10. Час Discord автоматично показується кожному у його локальному часовому поясі.*')

def fresh(): return {'channel_id':CHANNEL_ID,'message_id':None,'packs':[],'roles':{}}
def load():
    DATA.parent.mkdir(parents=True,exist_ok=True)
    if not DATA.exists(): return fresh()
    try: s=json.loads(DATA.read_text(encoding='utf-8'))
    except Exception as e:
        print('[LEAGUE LOAD]',e); return fresh()
    for k,v in fresh().items(): s.setdefault(k,v)
    for p in s['packs']:
        p.setdefault('members',[]); p.setdefault('pending',[]); p.setdefault('leader_role',None); p.setdefault('start_ts',None)
    return s
def save(s):
    DATA.parent.mkdir(parents=True,exist_ok=True); tmp=DATA.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(DATA)
def rt(k):
    r=ROLES.get(k); return f'{r[0]} {r[1]}' if r else '❔ роль не обрана'
def gp(s,n): return next((p for p in s['packs'] if int(p['number'])==int(n)),None)
def up(s,uid):
    uid=str(uid)
    for p in s['packs']:
        if str(p.get('leader_id'))==uid: return p,'leader'
        if any(str(x.get('user_id'))==uid for x in p['members']): return p,'member'
        if any(str(x.get('user_id'))==uid for x in p['pending']): return p,'pending'
    return None,None
def cnt(p): return 1+len(p['members'])
def dtime(ts): return f'<t:{int(ts)}:F>'
def status(p):
    if not p.get('start_ts'): return '🟣 Налаштування'
    return '✅ Повна' if cnt(p)>=MAX_MEMBERS else '🟢 Готова' if cnt(p)>=MIN_MEMBERS else '🟡 Формується'
def progress(p):
    n=cnt(p)
    return f'{n}/{MAX_MEMBERS}' if n>=MAX_MEMBERS else f'{n}/{MAX_MEMBERS} • можна грати' if n>=MIN_MEMBERS else f'{n}/{MAX_MEMBERS} • ще {MIN_MEMBERS-n} до мінімуму'

def dates():
    days=['Пн','Вт','Ср','Чт','Пт','Сб','Нд']; now=datetime.now(TZ); out=[]
    for i in range(14):
        d=(now+timedelta(days=i)).date(); weekend=d.weekday()>=5
        out.append(discord.SelectOption(label=f'{days[d.weekday()]}, {d:%d.%m.%Y}',value=d.isoformat(),description=('13:00 - 01:00 CET/CEST' if weekend else '17:00 - 01:00 CET/CEST')))
    return out
def slots(day):
    d=datetime.fromisoformat(day).date(); cur=datetime(d.year,d.month,d.day,13 if d.weekday()>=5 else 17,tzinfo=TZ); end=datetime(d.year,d.month,d.day,1,tzinfo=TZ)+timedelta(days=1); out=[]
    while cur<=end:
        out.append((cur.strftime('%H:%M')+(' (+1 день)' if cur.date()!=d else ''),int(cur.timestamp()))); cur+=timedelta(minutes=20)
    return out

def embed(n,p,bot):
    if not p:
        e=discord.Embed(title=f'Пачка {n} • не створена',description='Обери роль і натисни **Створити пачку**.\nТой, хто створить її, стане PL.',color=COLOR)
    else:
        lid=str(p['leader_id']); lr=p.get('leader_role'); ts=p.get('start_ts')
        desc=(f'🕒 {dtime(ts)}\n👑 **PL:** <@{lid}> • {rt(lr)}\n👥 **Склад:** {progress(p)}' if ts else f'👑 **PL:** <@{lid}> • {rt(lr)}\n🕒 **Час:** ще не обраний\nНатисни **Створити пачку** і задай день та час.')
        e=discord.Embed(title=f'Пачка {n} • {status(p)}',description=desc,color=COLOR)
        members=[f'👑 {rt(lr)} <@{lid}>']+[f"{rt(x.get('role'))} <@{x['user_id']}>" for x in p['members']]
        e.add_field(name=f'Учасники • {cnt(p)}/{MAX_MEMBERS}',value='\n'.join(members)[:1024],inline=False)
        if p['pending']:
            pend='\n'.join(f"⏳ {rt(x.get('role'))} <@{x['user_id']}>" for x in p['pending'])+'\nPL: **керування пачкою → Прийняти заявку**'
            e.add_field(name=f"Заявки • {len(p['pending'])}",value=pend[:1024],inline=False)
    e.set_footer(text=FOOTER,icon_url=bot.display_avatar.url if bot else None); return e

class Select(discord.ui.Select):
    def __init__(self,cog,kind,opts,meta=None,ph='Оберіть'):
        super().__init__(placeholder=ph,options=opts,min_values=1,max_values=1); self.cog,self.kind,self.meta=cog,kind,meta or {}
    async def callback(self,i):
        v=self.values[0]
        if self.kind=='pack': return await self.cog.signup_to(i,int(v),self.meta.get('move',False))
        if self.kind=='date': return await i.response.edit_message(content='**2/2. Обери час матчу:**',view=TimeView(self.cog,v,self.meta))
        if self.kind=='member': return await self.cog.member_action(i,self.meta['pack'],self.meta['action'],int(v))
class One(discord.ui.View):
    def __init__(self,s): super().__init__(timeout=180); self.add_item(s)
class TimeView(discord.ui.View):
    def __init__(self,cog,day,meta,page=0):
        super().__init__(timeout=180); ss=slots(day); sel=discord.ui.Select(placeholder='Час CET/CEST',options=[discord.SelectOption(label=a,value=str(b)) for a,b in ss[page*25:(page+1)*25]])
        async def chosen(i):
            ts=int(sel.values[0]); await (cog.create_finish(i,ts) if meta['mode']=='create' else cog.reschedule_finish(i,meta['pack'],ts))
        sel.callback=chosen; self.add_item(sel)
        if len(ss)>25:
            a=discord.ui.Button(label='Раніше',disabled=page==0); b=discord.ui.Button(label='Пізніше',disabled=(page+1)*25>=len(ss))
            async def prev(i): await i.response.edit_message(view=TimeView(cog,day,meta,max(0,page-1)))
            async def nxt(i): await i.response.edit_message(view=TimeView(cog,day,meta,page+1))
            a.callback,b.callback=prev,nxt; self.add_item(a); self.add_item(b)
class PLMenu(discord.ui.Select):
    def __init__(self,cog):
        acts=[('✅','Прийняти заявку','approve'),('❌','Відхилити заявку','reject'),('📋','Переглянути заявки','pending'),('🗑️','Видалити учасника','remove'),('📅','Змінити день / час','reschedule'),('👑','Передати PL','leader'),('🔄','Оновити панель','refresh'),('⛔','Скасувати пачку','cancel')]
        super().__init__(placeholder='PL: керування пачкою',custom_id='league_pl',row=3,options=[discord.SelectOption(emoji=e,label=l,value=v) for e,l,v in acts]); self.cog=cog
    async def callback(self,i): await self.cog.pl_action(i,self.values[0])
class MainView(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        for k,style in [('tank',discord.ButtonStyle.primary),('dps',discord.ButtonStyle.danger),('shai',discord.ButtonStyle.success)]:
            b=discord.ui.Button(label=ROLES[k][1],emoji=ROLES[k][0],style=style,custom_id=f'league_role_{k}',row=0)
            async def cb(i,key=k): await cog.set_role(i,key)
            b.callback=cb; self.add_item(b)
        acts=[('Записатися','✅',discord.ButtonStyle.success,'league_signup',lambda i:cog.begin_signup(i,False)),('Змінити пачку','🔁',discord.ButtonStyle.primary,'league_move',lambda i:cog.begin_signup(i,True)),('Вийти','✖️',discord.ButtonStyle.danger,'league_leave',cog.leave),('Створити пачку','➕',discord.ButtonStyle.secondary,'league_create',cog.begin_create)]
        for label,emo,style,cid,fn in acts:
            b=discord.ui.Button(label=label,emoji=emo,style=style,custom_id=cid,row=1 if cid!='league_create' else 2); b.callback=fn; self.add_item(b)
        self.add_item(PLMenu(cog))
class Cancel(discord.ui.View):
    def __init__(self,cog,n,uid): super().__init__(timeout=60); self.cog,self.n,self.uid=cog,n,uid
    @discord.ui.button(label='Так, скасувати',style=discord.ButtonStyle.danger)
    async def yes(self,i,_):
        if i.user.id!=self.uid: return await i.response.send_message('Це не твоє підтвердження.',ephemeral=True)
        await self.cog.cancel(i,self.n)
    @discord.ui.button(label='Ні',style=discord.ButtonStyle.secondary)
    async def no(self,i,_): await i.response.edit_message(content='Скасування відмінено.',view=None)

class GuildLeagueCog(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.state=load(); self.lock=asyncio.Lock()
    async def cog_load(self): self.bot.add_view(MainView(self))
    def save(self): save(self.state)
    async def ok(self,i):
        if i.guild_id==GUILD_ID and i.channel_id==CHANNEL_ID: return True
        await i.response.send_message(f'Працює тільки в <#{CHANNEL_ID}>.',ephemeral=True); return False
    async def panel_msg(self):
        mid=self.state.get('message_id')
        if not mid: return None
        ch=self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
        try: return await ch.fetch_message(int(mid))
        except: return None
    async def refresh(self):
        m=await self.panel_msg()
        if m: await m.edit(content=PANEL,embeds=[embed(n,gp(self.state,n),self.bot.user) for n in range(1,4)],view=MainView(self))
    async def set_role(self,i,key):
        if not await self.ok(i): return
        uid=str(i.user.id); self.state['roles'][uid]=key; p,kind=up(self.state,uid)
        if p:
            if kind=='leader': p['leader_role']=key
            else:
                for x in p['members']+p['pending']:
                    if str(x['user_id'])==uid: x['role']=key
        self.save(); await self.refresh(); await i.response.send_message(f'Твоя роль: **{rt(key)}**.',ephemeral=True)
    async def begin_signup(self,i,move):
        if not await self.ok(i): return
        uid=str(i.user.id); role=self.state['roles'].get(uid); cur,kind=up(self.state,uid)
        if not role: return await i.response.send_message('Спочатку обери **Tank**, **DPS** або **Shai**.',ephemeral=True)
        if move and not cur: return await i.response.send_message('Ти ще ніде не записаний. Натисни **Записатися**.',ephemeral=True)
        if move and kind=='leader': return await i.response.send_message('PL спочатку має передати PL або скасувати пачку.',ephemeral=True)
        if not move and cur: return await i.response.send_message(f"Ти вже пов'язаний з **Пачкою {cur['number']}**. Для зміни натисни **Змінити пачку**.",ephemeral=True)
        packs=[p for p in self.state['packs'] if p.get('start_ts') and cnt(p)<MAX_MEMBERS and (not cur or p['number']!=cur['number'])]
        if not packs: return await i.response.send_message('Немає доступної пачки з обраним часом.',ephemeral=True)
        lines=[]; opts=[]
        for p in packs:
            n=p['number']; member=i.guild.get_member(int(p['leader_id'])) if i.guild else None
            lines.append(f"**Пачка {n}** • {dtime(p['start_ts'])} • {cnt(p)}/{MAX_MEMBERS} • PL: <@{p['leader_id']}>")
            opts.append(discord.SelectOption(label=f'Пачка {n} • {cnt(p)}/{MAX_MEMBERS}',value=str(n),description=f"PL: {member.display_name if member else 'PL'}"))
        await i.response.send_message('\n'.join(lines)+'\n\n**Обери пачку:**',view=One(Select(self,'pack',opts,{'move':move},'Обрати пачку')),ephemeral=True)
    async def signup_to(self,i,n,move):
        async with self.lock:
            p=gp(self.state,n); uid=str(i.user.id); role=self.state['roles'].get(uid); cur,kind=up(self.state,uid)
            if not p or not p.get('start_ts') or cnt(p)>=MAX_MEMBERS: return await i.response.edit_message(content='Ця пачка вже недоступна.',view=None)
            if not role: return await i.response.edit_message(content='Спочатку обери роль.',view=None)
            if kind=='leader': return await i.response.edit_message(content='PL не може перейти напряму.',view=None)
            if cur:
                cur['members']=[x for x in cur['members'] if str(x['user_id'])!=uid]; cur['pending']=[x for x in cur['pending'] if str(x['user_id'])!=uid]
            p['pending']=[x for x in p['pending'] if str(x['user_id'])!=uid]; p['pending'].append({'user_id':uid,'role':role}); self.save(); await self.refresh()
            ch=self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
            await ch.send(f"<@{p['leader_id']}> нова заявка в **Пачку {n}**\n👤 <@{uid}> • {rt(role)}\n🕒 {dtime(p['start_ts'])}\nПрийняти: **PL: керування пачкою → Прийняти заявку**.",allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False))
        await i.response.edit_message(content=f"✅ Заявку в **Пачку {n}** надіслано.\n🕒 {dtime(p['start_ts'])}\nРоль: **{rt(role)}**\nПісля підтвердження ти з'явишся у складі.",view=None)
    async def leave(self,i):
        if not await self.ok(i): return
        p,kind=up(self.state,i.user.id)
        if not p: return await i.response.send_message('Ти не записаний у пачку.',ephemeral=True)
        if kind=='leader': return await i.response.send_message('PL спочатку має передати PL або скасувати пачку.',ephemeral=True)
        uid=str(i.user.id); n=p['number']; p['members']=[x for x in p['members'] if str(x['user_id'])!=uid]; p['pending']=[x for x in p['pending'] if str(x['user_id'])!=uid]; self.save(); await self.refresh(); await i.response.send_message(f'Ти вийшов із **Пачки {n}**.',ephemeral=True)
    async def begin_create(self,i):
        if not await self.ok(i): return
        uid=str(i.user.id); role=self.state['roles'].get(uid); cur,kind=up(self.state,uid)
        if not role: return await i.response.send_message('Спочатку обери **Tank**, **DPS** або **Shai**. PL входить у 10.',ephemeral=True)
        if cur and kind=='leader' and not cur.get('start_ts'): n=cur['number']
        elif cur: return await i.response.send_message('Ти вже в пачці. Щоб створити нову, спочатку вийди.',ephemeral=True)
        elif len(self.state['packs'])>=3: return await i.response.send_message('Уже створені всі 3 пачки.',ephemeral=True)
        else:
            n=len(self.state['packs'])+1; self.state['packs'].append({'number':n,'leader_id':uid,'leader_role':role,'start_ts':None,'members':[],'pending':[]}); self.save(); await self.refresh()
        s=Select(self,'date',dates(),{'mode':'create','pack':n},'День матчу'); await i.response.send_message(f'Ти PL **Пачки {n}**.\n**1/2. Обери день:**',view=One(s),ephemeral=True)
    async def create_finish(self,i,ts):
        async with self.lock:
            uid=str(i.user.id); p,kind=up(self.state,uid); role=self.state['roles'].get(uid)
            if not p or kind!='leader': return await i.response.edit_message(content='Ця пачка більше не твоя.',view=None)
            p['leader_role']=role; p['start_ts']=ts; n=p['number']; self.save(); await self.refresh(); ch=self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
            await ch.send(f'<@&{LEAGUE_ROLE_ID}> створена **Пачка {n}**\n🕒 {dtime(ts)}\n👑 PL: <@{uid}> • {rt(role)}\nДля участі обери роль і натисни **Записатися**.',allowed_mentions=discord.AllowedMentions(roles=True,users=True,everyone=False))
        await i.response.edit_message(content=f'✅ **Пачка {n} створена.**\n🕒 {dtime(ts)}\nТи PL і перший учасник: **{rt(role)}**.',view=None)
    async def pl_action(self,i,action):
        if not await self.ok(i): return
        p=next((x for x in self.state['packs'] if str(x['leader_id'])==str(i.user.id)),None)
        if not p: return await i.response.send_message('Це меню доступне тільки PL його пачки.',ephemeral=True)
        n=p['number']
        if action=='refresh': await self.refresh(); return await i.response.send_message('Панель оновлена.',ephemeral=True)
        if action=='pending':
            if not p['pending']: return await i.response.send_message(f'У **Пачки {n}** немає заявок.',ephemeral=True)
            text=f"**Заявки в Пачку {n}:**\n"+(f"🕒 {dtime(p['start_ts'])}\n" if p.get('start_ts') else '')+'\n'.join(f"• {rt(x['role'])} <@{x['user_id']}>" for x in p['pending'])+'\n\nЩоб прийняти: **PL: керування пачкою → Прийняти заявку**.'
            return await i.response.send_message(text,ephemeral=True)
        entries=p['pending'] if action in ('approve','reject') else p['members'] if action in ('remove','leader') else []
        if action in ('approve','reject','remove','leader'):
            if not entries: return await i.response.send_message('Заявок немає.' if action in ('approve','reject') else 'Немає кого обирати.',ephemeral=True)
            opts=[]
            for x in entries[:25]:
                m=i.guild.get_member(int(x['user_id'])) if i.guild else None; opts.append(discord.SelectOption(label=f"{m.display_name if m else x['user_id']} • {rt(x['role'])}"[:100],value=str(x['user_id'])))
            prompt={'approve':'**Кого прийняти?**','reject':'**Чию заявку відхилити?**','remove':'**Кого видалити?**','leader':'**Кому передати PL?**'}[action]
            return await i.response.send_message(prompt,view=One(Select(self,'member',opts,{'pack':n,'action':action},'Обрати учасника')),ephemeral=True)
        if action=='reschedule': return await i.response.send_message(f'**Пачка {n}: зміна часу**\n**1/2. Обери день:**',view=One(Select(self,'date',dates(),{'mode':'reschedule','pack':n},'Новий день')),ephemeral=True)
        if action=='cancel': return await i.response.send_message(f'Скасувати **Пачку {n}**? Усі записи та заявки буде видалено.',view=Cancel(self,n,i.user.id),ephemeral=True)
    async def member_action(self,i,n,action,target):
        async with self.lock:
            p=gp(self.state,n); uid=str(target)
            if not p or str(p['leader_id'])!=str(i.user.id): return await i.response.edit_message(content='Ти більше не PL цієї пачки.',view=None)
            if action=='approve':
                if cnt(p)>=MAX_MEMBERS: return await i.response.edit_message(content=f'Пачка вже {MAX_MEMBERS}/{MAX_MEMBERS}.',view=None)
                x=next((x for x in p['pending'] if str(x['user_id'])==uid),None)
                if not x: return await i.response.edit_message(content='Цієї заявки вже немає.',view=None)
                p['pending'].remove(x); p['members'].append(x); msg=f'✅ <@{uid}> прийнято в **Пачку {n}**. Склад: **{cnt(p)}/{MAX_MEMBERS}**'
            elif action=='reject': p['pending']=[x for x in p['pending'] if str(x['user_id'])!=uid]; msg=f'❌ Заявку <@{uid}> відхилено.'
            elif action=='remove': p['members']=[x for x in p['members'] if str(x['user_id'])!=uid]; msg=f'🗑️ <@{uid}> видалено з **Пачки {n}**.'
            else:
                x=next((x for x in p['members'] if str(x['user_id'])==uid),None)
                if not x: return await i.response.edit_message(content='Цього учасника вже немає.',view=None)
                old={'user_id':str(p['leader_id']),'role':p.get('leader_role')}; p['members'].remove(x); p['members'].insert(0,old); p['leader_id']=uid; p['leader_role']=x['role']; msg=f'👑 PL **Пачки {n}** передано <@{uid}>.'
            self.save(); await self.refresh()
        await i.response.edit_message(content=msg,view=None)
    async def reschedule_finish(self,i,n,ts):
        p=gp(self.state,n)
        if not p or str(p['leader_id'])!=str(i.user.id): return await i.response.edit_message(content='Ти більше не PL.',view=None)
        p['start_ts']=ts; self.save(); await self.refresh(); await i.response.edit_message(content=f'✅ Час **Пачки {n}** змінено.\n🕒 {dtime(ts)}',view=None)
    async def cancel(self,i,n):
        p=gp(self.state,n)
        if not p or str(p['leader_id'])!=str(i.user.id): return await i.response.edit_message(content='Ти більше не PL.',view=None)
        self.state['packs']=[x for x in self.state['packs'] if x['number']!=n]
        for j,x in enumerate(self.state['packs'],1): x['number']=j
        self.save(); await self.refresh(); await i.response.edit_message(content=f'Пачку {n} скасовано. Нумерацію оновлено.',view=None)
    async def first(self,i):
        if self.state['packs']: return
        uid=str(i.user.id); self.state['packs'].append({'number':1,'leader_id':uid,'leader_role':self.state['roles'].get(uid),'start_ts':None,'members':[],'pending':[]}); self.save()
    @app_commands.command(name='guild_league_panel',description='Створити або оновити панель Ліги гільдій')
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def panel(self,i):
        admin=i.user.guild_permissions.administrator; has=isinstance(i.user,discord.Member) and any(r.id==LEAGUE_ROLE_ID for r in i.user.roles)
        if not(admin or has): return await i.response.send_message(f'Команда доступна учасникам <@&{LEAGUE_ROLE_ID}>.',ephemeral=True)
        if i.channel_id!=CHANNEL_ID: return await i.response.send_message(f'Запусти команду в <#{CHANNEL_ID}>.',ephemeral=True)
        await self.first(i); em=[embed(n,gp(self.state,n),self.bot.user) for n in range(1,4)]; old=await self.panel_msg()
        if old: await old.edit(content=PANEL,embeds=em,view=MainView(self)); return await i.response.send_message(f'Панель оновлена: {old.jump_url}',ephemeral=True)
        await i.response.send_message(content=PANEL,embeds=em,view=MainView(self)); m=await i.original_response(); self.state['message_id']=m.id; self.save()

async def setup(bot): await bot.add_cog(GuildLeagueCog(bot))
