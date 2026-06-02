import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import datetime
import os
import io
import aiohttp
from PIL import Image
from dotenv import load_dotenv
from typing import Optional, List, Union

# Carregar variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    TOKEN = TOKEN.strip().replace('"', '').replace("'", "")

# Configuração do Bot
class TheBoysBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True # Necessário para alguns comandos sociais
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Comandos sincronizados para {self.user}")

bot = TheBoysBot()

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Usuários
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (discord_id INTEGER PRIMARY KEY, 
                  team TEXT, 
                  favorite_card_id INTEGER,
                  partner_id INTEGER, -- Pode ser ID de usuário ou ID de carta (negativo para carta)
                  partner_type TEXT, -- 'user' ou 'card'
                  last_drop TEXT,
                  last_salary TEXT,
                  last_mystery TEXT,
                  balance INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  custom_name TEXT,
                  custom_image TEXT,
                  bio TEXT,
                  embed_color TEXT DEFAULT '000000',
                  aesthetic_id TEXT DEFAULT 'default')''')
    
    # Cartas
    c.execute('''CREATE TABLE IF NOT EXISTS cards 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, 
                  category TEXT, -- Normal, Comemorativa, Especial, Duo, Casal
                  tag TEXT, 
                  image_url TEXT,
                  evolved_image_url TEXT)''')
    
    # Inventário
    c.execute('''CREATE TABLE IF NOT EXISTS inventory 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id INTEGER, 
                  card_id INTEGER, 
                  amount INTEGER DEFAULT 1,
                  level INTEGER DEFAULT 0, -- 0: Normal, 1: 1 Estrela, 2: 2 Estrelas, 3: 3 Estrelas, 4: Coroada
                  frame_id INTEGER,
                  card_wins INTEGER DEFAULT 0,
                  UNIQUE(user_id, card_id, level),
                  FOREIGN KEY(user_id) REFERENCES users(discord_id),
                  FOREIGN KEY(card_id) REFERENCES cards(id))''')
    
    # Tentar adicionar a coluna card_wins caso a tabela já exista
    try:
        c.execute("ALTER TABLE inventory ADD COLUMN card_wins INTEGER DEFAULT 0")
    except:
        pass

    # Loja (Shopping)
    c.execute('''CREATE TABLE IF NOT EXISTS shop 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  item_type TEXT, -- 'aesthetic', 'frame', 'card'
                  item_id TEXT, 
                  name TEXT,
                  price INTEGER)''')

    # Molduras (Frames)
    c.execute('''CREATE TABLE IF NOT EXISTS frames 
                 (id INTEGER PRIMARY KEY, 
                  name TEXT, 
                  image_url TEXT)''')

    # Receitas de Combinação (Duo/Casal)
    c.execute('''CREATE TABLE IF NOT EXISTS recipes 
                 (card_a_id INTEGER, 
                  card_b_id INTEGER, 
                  result_card_id INTEGER)''')

    # Inventário de Cosméticos (Frames comprados)
    c.execute('''CREATE TABLE IF NOT EXISTS user_cosmetics 
                 (user_id INTEGER, 
                  item_type TEXT, 
                  item_id TEXT)''')

    conn.commit()
    conn.close()

init_db()

# --- CLASSES E UTILITÁRIOS ---

class BattleModal(discord.ui.Modal, title="Escolha sua Carta para a Batalha"):
    card_id = discord.ui.TextInput(label="ID da Carta", placeholder="Digite o código da carta que deseja usar...", required=True)
    def __init__(self, target, challenger, challenger_card_id, challenger_level):
        super().__init__()
        self.target = target
        self.challenger = challenger
        self.challenger_card_id = challenger_card_id
        self.challenger_level = challenger_level

    async def on_submit(self, interaction: discord.Interaction):
        try:
            op_card_id = int(self.card_id.value)
        except ValueError:
            return await interaction.response.send_message("❌ ID inválido!", ephemeral=True)

        conn = sqlite3.connect('the_boys_bot.db')
        c = conn.cursor()
        c.execute("SELECT level FROM inventory WHERE user_id = ? AND card_id = ? ORDER BY level DESC LIMIT 1", (self.target.id, op_card_id))
        row = c.fetchone()
        
        if not row:
            conn.close()
            return await interaction.response.send_message("❌ Você não possui esta carta!", ephemeral=True)
        
        op_level = row[0]
        power_map = {0: 10, 1: 25, 2: 50, 3: 100, 4: 200}
        user_power = random.randint(1, power_map[self.challenger_level])
        op_power = random.randint(1, power_map[op_level])
        
        vencedor = self.challenger if user_power >= op_power else self.target
        c.execute("UPDATE users SET wins = wins + 1 WHERE discord_id = ?", (vencedor.id,))
        
        if vencedor == self.challenger:
            c.execute("UPDATE inventory SET card_wins = card_wins + 1 WHERE user_id = ? AND card_id = ? AND level = ?", (self.challenger.id, self.challenger_card_id, self.challenger_level))
        else:
            c.execute("UPDATE inventory SET card_wins = card_wins + 1 WHERE user_id = ? AND card_id = ? AND level = ?", (self.target.id, op_card_id, op_level))
        
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"🥊 **Fim da Batalha!**\n{self.challenger.name} ({user_power} pts) vs {self.target.name} ({op_power} pts)\n🏆 Vencedor: **{vencedor.mention}**!")

class ConfirmInteraction(discord.ui.View):
    def __init__(self, target, challenger, challenger_card_id=None, challenger_level=None, timeout=60):
        super().__init__(timeout=timeout)
        self.target = target
        self.challenger = challenger
        self.challenger_card_id = challenger_card_id
        self.challenger_level = challenger_level
        self.value = None

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.green)
    async def accept(self, interaction, button):
        if interaction.user != self.target: return
        self.value = True
        self.stop()
        await interaction.response.send_modal(BattleModal(self.target, self.challenger, self.challenger_card_id, self.challenger_level))

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.red)
    async def decline(self, interaction, button):
        if interaction.user != self.target: return
        self.value = False
        self.stop()
        await interaction.response.send_message("🏳️ O desafio foi recusado.")

def get_user_db(user_id):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE discord_id = ?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users (discord_id) VALUES (?)", (user_id,))
        conn.commit()
        c.execute("SELECT * FROM users WHERE discord_id = ?", (user_id,))
        user = c.fetchone()
    conn.close()
    return user

async def get_card_image_with_frame(card_url, frame_url):
    async with aiohttp.ClientSession() as session:
        async with session.get(card_url) as resp:
            if resp.status != 200: return card_url
            card_bytes = io.BytesIO(await resp.read())
        async with session.get(frame_url) as resp:
            if resp.status != 200: return card_url
            frame_bytes = io.BytesIO(await resp.read())
    
    card_img = Image.open(card_bytes).convert("RGBA")
    frame_img = Image.open(frame_bytes).convert("RGBA")
    
    # Redimensionar moldura para o tamanho da carta
    frame_img = frame_img.resize(card_img.size, Image.Resampling.LANCZOS)
    
    # Sobrepor
    combined = Image.alpha_composite(card_img, frame_img)
    
    # Salvar temporariamente
    output = io.BytesIO()
    combined.save(output, format="PNG")
    output.seek(0)
    return output

# --- CORES E EMOJIS ---
def get_aesthetic_emojis():
    return ['👤','📊','🏆','🏢','⭐','💰']

def get_ranking_pos(user_id):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute('''SELECT users.discord_id, SUM(inventory.amount) as total 
                 FROM users 
                 LEFT JOIN inventory ON users.discord_id = inventory.user_id 
                 GROUP BY users.discord_id 
                 ORDER BY total DESC''')
    rows = c.fetchall()
    conn.close()
    for idx, row in enumerate(rows):
        if row[0] == user_id:
            return idx + 1
    return "N/A"

# --- COMANDOS DE ECONOMIA ---

@bot.tree.command(name="salario", description="Receba seu salário diário de $200.")
async def salario(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = get_user_db(user_id)
    
    now = datetime.datetime.now()
    if user_data[6]: # last_salary
        last_salary = datetime.datetime.fromisoformat(user_data[6])
        if (now - last_salary).days < 1:
            proximo = last_salary + datetime.timedelta(days=1)
            espera = proximo - now
            horas = espera.seconds // 3600
            minutos = (espera.seconds // 60) % 60
            return await interaction.response.send_message(f"⌛ Você já recebeu seu salário hoje! Volte em {horas}h {minutos}min.", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + 200, last_salary = ? WHERE discord_id = ?", (now.isoformat(), user_id))
    conn.commit()
    conn.close()
    
    await interaction.response.send_message(f"💰 **Salário Recebido!** Você ganhou **$200** moedas da Vought.")

# --- COMANDOS DE PERFIL ---

@bot.tree.command(name="setname", description="Define o nome do seu perfil.")
async def setname(interaction: discord.Interaction, nome: str):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET custom_name = ? WHERE discord_id = ?", (nome, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Nome alterado para: **{nome}**")

@bot.tree.command(name="setbio", description="Define a bio do seu perfil.")
async def setbio(interaction: discord.Interaction, bio: str):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET bio = ? WHERE discord_id = ?", (bio, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Bio atualizada!")

@bot.tree.command(name="setcolor", description="Define a cor do seu perfil (Hexadecimal, ex: FF0000).")
async def setcolor(interaction: discord.Interaction, hex_color: str):
    # Validar Hex
    hex_color = hex_color.replace("#", "")
    if len(hex_color) != 6:
        return await interaction.response.send_message("❌ Cor inválida! Use o formato hexadecimal de 6 dígitos (ex: FF0000).", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET embed_color = ? WHERE discord_id = ?", (hex_color, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Cor do perfil alterada!")

@bot.tree.command(name="carreira", description="Veja seu perfil completo.")
async def carreira(interaction: discord.Interaction, membro: Optional[discord.Member] = None):
    target = membro or interaction.user
    user_data = get_user_db(target.id)
    
    # Emojis do Aesthetic
    emojis = get_aesthetic_emojis()
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM inventory WHERE user_id = ?", (target.id,))
    total_cards = c.fetchone()[0] or 0
    
    # Ranking
    ranking = get_ranking_pos(target.id)
    
    # Favorito (Amor)
    fav_card = None
    if user_data[2]:
        c.execute("SELECT name FROM cards WHERE id = ?", (user_data[2],))
        fav_card = c.fetchone()
    
    # Parceiro (Casamento)
    parceiro_text = "Ninguém"
    if user_data[3]: # partner_id
        if user_data[4] == 'user':
            p_user = bot.get_user(user_data[3])
            parceiro_text = p_user.name if p_user else f"Usuário {user_data[3]}"
        else:
            c.execute("SELECT name FROM cards WHERE id = ?", (user_data[3],))
            p_card = c.fetchone()
            parceiro_text = p_card[0] if p_card else "Uma Carta"
    
    conn.close()
    
    color = int(user_data[13] or "000000", 16)
    display_name = user_data[10] or target.name
    
    embed = discord.Embed(title=f"📁 Dossier: {display_name}", description=user_data[12] or "Sem bio definida.", color=color)
    embed.add_field(name=f"{emojis[0]} Nome", value=display_name, inline=True)
    embed.add_field(name=f"{emojis[1]} Cartas", value=str(total_cards), inline=True)
    embed.add_field(name=f"{emojis[2]} Rank", value=f"#{ranking}", inline=True)
    embed.add_field(name=f"{emojis[3]} Time", value=user_data[1] or "Nenhum", inline=True)
    embed.add_field(name=f"{emojis[4]} Seu Amor", value=fav_card[0] if fav_card else "Ninguém", inline=True)
    embed.add_field(name=f"💍 Parceiro", value=parceiro_text, inline=True)
    embed.add_field(name=f"⚔️ Vitórias", value=str(user_data[9] or 0), inline=True)
    embed.add_field(name=f"{emojis[5]} Moedas", value=f"${user_data[8] or 0}", inline=True)
    
    # Foto de Perfil Grande (Image)
    if user_data[11]: # custom_image
        embed.set_image(url=user_data[11])
    
    # Carta Favorita Pequena (Thumbnail)
    if user_data and user_data[2]: # favorite_card_id
        conn = sqlite3.connect('the_boys_bot.db')
        c = conn.cursor()
        c.execute("SELECT image_url FROM cards WHERE id = ?", (user_data[2],))
        fav_img = c.fetchone()
        conn.close()
        if fav_img:
            embed.set_thumbnail(url=fav_img[0])
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ranking", description="Mostra o ranking dos jogadores.")
async def ranking(interaction: discord.Interaction):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute('''SELECT users.discord_id, users.custom_name, SUM(inventory.amount) as total 
                 FROM users 
                 LEFT JOIN inventory ON users.discord_id = inventory.user_id 
                 GROUP BY users.discord_id 
                 ORDER BY total DESC LIMIT 10''')
    top_players = c.fetchall()
    conn.close()
    
    desc = ""
    for idx, row in enumerate(top_players):
        user = bot.get_user(row[0])
        name = row[1] or (user.name if user else f"Usuário {row[0]}")
        total = row[2] or 0
        desc += f"**{idx+1}. {name}** — {total} cartas\n"
    
    embed = discord.Embed(title="🏆 Ranking Global da Vought", description=desc or "Nenhum jogador no ranking ainda.", color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="setimage", description="Define sua foto de perfil (Anexe uma imagem).")
async def setimage(interaction: discord.Interaction, imagem: discord.Attachment):
    if not imagem.content_type.startswith("image/"):
        return await interaction.response.send_message("❌ O arquivo anexado deve ser uma imagem!", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET custom_image = ? WHERE discord_id = ?", (imagem.url, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Imagem de perfil atualizada com sucesso!")

@bot.tree.command(name="moedas", description="Veja seu saldo de moedas.")
async def moedas(interaction: discord.Interaction):
    user_data = get_user_db(interaction.user.id)
    await interaction.response.send_message(f"💰 Você possui **${user_data[8] or 0}** moedas da Vought.")

@bot.tree.command(name="recrutar", description="Dropa uma carta aleatória a cada 10 minutos.")
async def recrutar(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = get_user_db(user_id)
    
    now = datetime.datetime.now()
    if user_data[5]: # last_drop
        last_drop = datetime.datetime.fromisoformat(user_data[5])
        if (now - last_drop).total_seconds() < 600:
            espera = int(600 - (now - last_drop).total_seconds())
            return await interaction.response.send_message(f"⌛ Aguarde {espera // 60}m {espera % 60}s para recrutar novamente.", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    # Drop igualitário: Selecionar aleatoriamente sem pesos
    c.execute("SELECT * FROM cards WHERE category NOT IN ('Especial', 'Comemorativa', 'Duo', 'Casal') ORDER BY RANDOM() LIMIT 1")
    card = c.fetchone()
    
    if not card:
        conn.close()
        return await interaction.response.send_message("❌ Nenhuma carta comum cadastrada no sistema!", ephemeral=True)
    
    c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (user_id, card[0]))
    c.execute("UPDATE users SET last_drop = ? WHERE discord_id = ?", (now.isoformat(), user_id))
    conn.commit()
    conn.close()
    
    embed = discord.Embed(title="🎖️ Novo Recruta Encontrado!", color=discord.Color.red())
    embed.add_field(name="Nome", value=card[1], inline=True)
    embed.add_field(name="Time", value=card[3], inline=True)
    embed.set_image(url=card[4])
    embed.set_footer(text=f"ID: #{card[0]}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="catalogo", description="Mostra todas as cartas do sistema.")
@app_commands.choices(categoria=[
    app_commands.Choice(name="Normal", value="Normal"),
    app_commands.Choice(name="Comemorativa", value="Comemorativa"),
    app_commands.Choice(name="Especial", value="Especial"),
    app_commands.Choice(name="Duo", value="Duo"),
    app_commands.Choice(name="Casal", value="Casal")
])
async def catalogo(interaction: discord.Interaction, categoria: Optional[str] = None, time: Optional[str] = None):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    query = "SELECT id, name, category, tag FROM cards"
    params = []
    if categoria or time:
        query += " WHERE"
        if categoria:
            query += " category = ?"
            params.append(categoria)
        if time:
            if categoria: query += " AND"
            query += " tag = ?"
            params.append(time)
    
    c.execute(query, tuple(params))
    cards = c.fetchall()
    conn.close()
    
    if not cards:
        return await interaction.response.send_message("❌ Nenhuma carta encontrada com esses filtros.", ephemeral=True)
    
    desc = "\n".join([f"`#{c[0]}` **{c[1]}** ({c[2]} - {c[3]})" for c in cards])
    embed = discord.Embed(title="🗃️ Catálogo da Vought", description=desc[:4000], color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="admirar", description="Veja detalhes de uma carta específica.")
async def admirar(interaction: discord.Interaction, codigo: int):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT name, category, tag, image_url, evolved_image_url FROM cards WHERE id = ?", (codigo,))
    card = c.fetchone()
    
    if not card:
        conn.close()
        return await interaction.response.send_message("❌ Carta não encontrada!", ephemeral=True)
    
    c.execute("SELECT amount, level, card_wins FROM inventory WHERE user_id = ? AND card_id = ?", (interaction.user.id, codigo))
    inv = c.fetchall()
    conn.close()
    
    level_names = {0: "Normal", 1: "1 Estrela ⭐", 2: "2 Estrelas ⭐⭐", 3: "3 Estrelas ⭐⭐⭐", 4: "Coroada 👑"}
    
    embed = discord.Embed(title=f"🔍 Admirando: {card[0]}", color=discord.Color.purple())
    embed.add_field(name="Categoria", value=card[1], inline=True)
    embed.add_field(name="Time", value=card[2], inline=True)
    
    if inv:
        status = "\n".join([f"**{level_names[i[1]]}**: {i[0]} unidades (⚔️ {i[2]} vitórias)" for i in inv])
        embed.add_field(name="No seu Inventário", value=status, inline=False)
        # Mostrar imagem evoluída se tiver a coroada
        has_coroada = any(i[1] == 4 for i in inv)
        img = card[4] if (has_coroada and card[4]) else card[3]
        embed.set_image(url=img)
    else:
        embed.add_field(name="Status", value="Você não possui esta carta.", inline=False)
        embed.set_image(url=card[3])
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="injetarv", description="Evolua suas cartas usando Composto V.")
async def injetarv(interaction: discord.Interaction, codigo: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Buscar inventário da carta para o nível atual
    # Regra: 10 normais -> 1 estrela | 2 de 1 estrela -> 2 estrelas | 2 de 2 estrelas -> 3 estrelas | 2 de 3 estrelas -> Coroada
    
    c.execute("SELECT level, amount FROM inventory WHERE user_id = ? AND card_id = ? ORDER BY level ASC", (user_id, codigo))
    inv = c.fetchall()
    
    if not inv:
        conn.close()
        return await interaction.response.send_message("❌ Você não possui esta carta!", ephemeral=True)
    
    current_levels = {row[0]: row[1] for row in inv}
    
    success = False
    new_level = 0
    
    if 0 in current_levels and current_levels[0] >= 10:
        # Normal -> 1 Estrela
        c.execute("UPDATE inventory SET amount = amount - 10 WHERE user_id = ? AND card_id = ? AND level = 0", (user_id, codigo))
        new_level = 1
        success = True
    elif 1 in current_levels and current_levels[1] >= 2:
        # 1 Estrela -> 2 Estrelas
        c.execute("UPDATE inventory SET amount = amount - 2 WHERE user_id = ? AND card_id = ? AND level = 1", (user_id, codigo))
        new_level = 2
        success = True
    elif 2 in current_levels and current_levels[2] >= 2:
        # 2 Estrelas -> 3 Estrelas
        c.execute("UPDATE inventory SET amount = amount - 2 WHERE user_id = ? AND card_id = ? AND level = 2", (user_id, codigo))
        new_level = 3
        success = True
    elif 3 in current_levels and current_levels[3] >= 2:
        # 3 Estrelas -> Coroada
        c.execute("UPDATE inventory SET amount = amount - 2 WHERE user_id = ? AND card_id = ? AND level = 3", (user_id, codigo))
        new_level = 4
        success = True
    
    if success:
        c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, ?) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (user_id, codigo, new_level))
        c.execute("DELETE FROM inventory WHERE amount <= 0")
        conn.commit()
        conn.close()
        level_names = {1: "1 Estrela ⭐", 2: "2 Estrelas ⭐⭐", 3: "3 Estrelas ⭐⭐⭐", 4: "Coroada 👑"}
        await interaction.response.send_message(f"🧪 **Composto V Injetado!** Sua carta agora é nível **{level_names[new_level]}**.")
    else:
        conn.close()
        await interaction.response.send_message("❌ Você não tem cartas suficientes para evoluir! (Precisa de 10 normais ou 2 do nível anterior).", ephemeral=True)

@bot.tree.command(name="batalha", description="Desafie um membro para uma batalha de cartas.")
async def batalha(interaction: discord.Interaction, oponente: discord.Member, codigo_sua_carta: int):
    if oponente.id == interaction.user.id:
        return await interaction.response.send_message("❌ Você não pode lutar contra si mesmo!", ephemeral=True)
    
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT level FROM inventory WHERE user_id = ? AND card_id = ? ORDER BY level DESC LIMIT 1", (user_id, codigo_sua_carta))
    row = c.fetchone()
    if not row:
        conn.close()
        return await interaction.response.send_message("❌ Você não possui esta carta!", ephemeral=True)
    
    user_level = row[0]
    conn.close()

    view = ConfirmInteraction(oponente, interaction.user, codigo_sua_carta, user_level)
    await interaction.response.send_message(f"⚔️ {oponente.mention}, você foi desafiado por {interaction.user.mention}! Aceita lutar?", view=view)

@bot.tree.command(name="casar", description="Case-se com um usuário ou uma carta.")
@app_commands.choices(tipo=[app_commands.Choice(name="Usuário", value="user"), app_commands.Choice(name="Carta", value="card")])
async def casar(interaction: discord.Interaction, tipo: str, alvo_id: str):
    user_id = interaction.user.id
    user_data = get_user_db(user_id)
    
    if user_data[3]: # partner_id
        return await interaction.response.send_message("❌ Você já está casado! Divorcie-se primeiro.", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    if tipo == "user":
        target_user = bot.get_user(int(alvo_id))
        if not target_user:
            conn.close()
            return await interaction.response.send_message("❌ Usuário não encontrado!", ephemeral=True)
        
        view = ConfirmInteraction(target_user, interaction.user)
        await interaction.response.send_message(f"💍 {target_user.mention}, {interaction.user.mention} quer se casar com você! Aceita?", view=view)
        await view.wait()
        if view.value:
            c.execute("UPDATE users SET partner_id = ?, partner_type = 'user' WHERE discord_id = ?", (target_user.id, user_id))
            c.execute("UPDATE users SET partner_id = ?, partner_type = 'user' WHERE discord_id = ?", (user_id, target_user.id))
            conn.commit()
            await interaction.followup.send(f"🎉 **{interaction.user.name}** e **{target_user.name}** agora estão casados!")
        else:
            await interaction.followup.send("💔 O pedido de casamento foi recusado.")
    else:
        # Casar com carta
        c.execute("SELECT name FROM cards WHERE id = ?", (int(alvo_id),))
        card = c.fetchone()
        if not card:
            conn.close()
            return await interaction.response.send_message("❌ Carta não encontrada!", ephemeral=True)
        
        c.execute("UPDATE users SET partner_id = ?, partner_type = 'card' WHERE discord_id = ?", (int(alvo_id), user_id))
        conn.commit()
        await interaction.response.send_message(f"💍 Você agora está casado com a carta **{card[0]}**!")
    
    conn.close()

@bot.tree.command(name="divorciar", description="Divorcie-se do seu parceiro atual.")
async def divorciar(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = get_user_db(user_id)
    
    if not user_data[3]:
        return await interaction.response.send_message("❌ Você não está casado!", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    if user_data[4] == 'user':
        # Remover de ambos
        c.execute("UPDATE users SET partner_id = NULL, partner_type = NULL WHERE discord_id = ?", (user_data[3],))
    
    c.execute("UPDATE users SET partner_id = NULL, partner_type = NULL WHERE discord_id = ?", (user_id,))
    conn.commit()
    conn.close()
    await interaction.response.send_message("💔 Você se divorciou com sucesso.")

@bot.tree.command(name="trocar", description="Troque uma carta com outro jogador.")
async def trocar(interaction: discord.Interaction, oponente: discord.Member, sua_carta_id: int, carta_dele_id: int):
    # Verificação de posse
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT amount FROM inventory WHERE user_id = ? AND card_id = ?", (interaction.user.id, sua_carta_id))
    u_card = c.fetchone()
    c.execute("SELECT amount FROM inventory WHERE user_id = ? AND card_id = ?", (oponente.id, carta_dele_id))
    o_card = c.fetchone()
    
    if not u_card or not o_card:
        conn.close()
        return await interaction.response.send_message("❌ Um de vocês não possui a carta mencionada!", ephemeral=True)
    
    view = ConfirmInteraction(oponente, interaction.user)
    await interaction.response.send_message(f"🤝 {oponente.mention}, {interaction.user.mention} quer trocar a carta #{sua_carta_id} pela sua #{carta_dele_id}. Aceita?", view=view)
    await view.wait()
    if view.value:
        # Lógica de troca
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND card_id = ?", (interaction.user.id, sua_carta_id))
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND card_id = ?", (oponente.id, carta_dele_id))
        c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (interaction.user.id, carta_dele_id))
        c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (oponente.id, sua_carta_id))
        c.execute("DELETE FROM inventory WHERE amount <= 0")
        conn.commit()
        await interaction.followup.send("✅ Troca realizada!")
    else:
        await interaction.followup.send("❌ Troca cancelada.")
    conn.close()

@bot.tree.command(name="caridade", description="Doe uma carta ou moedas para alguém.")
async def caridade(interaction: discord.Interaction, beneficiario: discord.Member, carta_id: Optional[int] = None, moedas: Optional[int] = None):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    if moedas:
        c.execute("SELECT balance FROM users WHERE discord_id = ?", (user_id,))
        balance = c.fetchone()[0]
        if balance < moedas:
            conn.close()
            return await interaction.response.send_message("❌ Saldo insuficiente!", ephemeral=True)
        c.execute("UPDATE users SET balance = balance - ? WHERE discord_id = ?", (moedas, user_id))
        c.execute("UPDATE users SET balance = balance + ? WHERE discord_id = ?", (moedas, beneficiario.id))
        await interaction.response.send_message(f"🎁 Você doou **${moedas}** para {beneficiario.name}!")
    
    if carta_id:
        c.execute("SELECT amount FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, carta_id))
        row = c.fetchone()
        if not row:
            conn.close()
            return await interaction.response.send_message("❌ Você não tem essa carta!", ephemeral=True)
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND card_id = ?", (user_id, carta_id))
        c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (beneficiario.id, carta_id))
        c.execute("DELETE FROM inventory WHERE amount <= 0")
        await interaction.response.send_message(f"🎁 Você doou a carta **#{carta_id}** para {beneficiario.name}!")
    
    conn.commit()
    conn.close()

@bot.tree.command(name="shopping", description="Acesse a loja da Vought.")
async def shopping(interaction: discord.Interaction):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM shop")
    items = c.fetchall()
    conn.close()
    
    if not items:
        return await interaction.response.send_message("🛒 A loja está vazia no momento!", ephemeral=True)
    
    desc = ""
    for item in items:
        desc += f"`ID: {item[2]}` **{item[3]}** — ${item[4]}\n"
    
    embed = discord.Embed(title="🛒 Shopping Vought International", description=desc, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="comprar", description="Compre um item da loja.")
async def comprar(interaction: discord.Interaction, item_id: str):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Verificar item
    c.execute("SELECT * FROM shop WHERE item_id = ?", (item_id,))
    item = c.fetchone()
    if not item:
        conn.close()
        return await interaction.response.send_message("❌ Item não encontrado!", ephemeral=True)
    
    # Verificar saldo
    c.execute("SELECT balance FROM users WHERE discord_id = ?", (user_id,))
    balance = c.fetchone()[0]
    if balance < item[4]:
        conn.close()
        return await interaction.response.send_message("❌ Saldo insuficiente!", ephemeral=True)
    
    # Processar compra
    c.execute("UPDATE users SET balance = balance - ? WHERE discord_id = ?", (item[4], user_id))
    c.execute("INSERT INTO user_cosmetics (user_id, item_type, item_id) VALUES (?, ?, ?)", (user_id, item[1], item_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Você comprou **{item[3]}** com sucesso!")



@bot.tree.command(name="enfeitar", description="Adiciona uma moldura em uma carta.")
async def enfeitar(interaction: discord.Interaction, codigo_moldura: str, codigo_carta: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Verificar moldura e carta
    c.execute("SELECT * FROM user_cosmetics WHERE user_id = ? AND item_id = ?", (user_id, codigo_moldura))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message("❌ Você não possui esta moldura!", ephemeral=True)
    
    c.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, codigo_carta))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message("❌ Você não possui esta carta!", ephemeral=True)
    
    c.execute("UPDATE inventory SET frame_id = ? WHERE user_id = ? AND card_id = ?", (codigo_moldura, user_id, codigo_carta))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Moldura aplicada à carta #{codigo_carta}!")

class BingoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.participants = []
    @discord.ui.button(label="Participar!", style=discord.ButtonStyle.blurple, emoji="🎱")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.participants:
            self.participants.append(interaction.user)
            await interaction.response.send_message("✅ Você entrou no bingo!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Você já está participando!", ephemeral=True)

@bot.tree.command(name="bingo", description="Inicia uma partida de bingo valendo $150.")
async def bingo(interaction: discord.Interaction):
    view = BingoView()
    await interaction.response.send_message("🎱 **BINGO DA VOUGHT!** Clique no botão abaixo para participar! (Sorteio em 30s)", view=view)
    await view.wait()
    if not view.participants:
        return await interaction.followup.send("☹️ Ninguém participou do bingo.")
    vencedor = random.choice(view.participants)
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + 150 WHERE discord_id = ?", (vencedor.id,))
    conn.commit()
    conn.close()
    await interaction.followup.send(f"🎉 **BINGO!** O ganhador foi {vencedor.mention} e recebeu **$150** moedas!")

class RestaUmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.choices = {}
    @discord.ui.button(label="1", style=discord.ButtonStyle.gray)
    async def one(self, interaction, button): await self.pick(interaction, 1)
    @discord.ui.button(label="2", style=discord.ButtonStyle.gray)
    async def two(self, interaction, button): await self.pick(interaction, 2)
    @discord.ui.button(label="3", style=discord.ButtonStyle.gray)
    async def three(self, interaction, button): await self.pick(interaction, 3)
    async def pick(self, interaction, num):
        self.choices[interaction.user] = num
        await interaction.response.send_message(f"✅ Você escolheu o número {num}!", ephemeral=True)

@bot.tree.command(name="restaum", description="Jogo de Resta Um valendo $150.")
async def restaum(interaction: discord.Interaction):
    view = RestaUmView()
    await interaction.response.send_message("🔢 **RESTA UM!** Escolha um número abaixo para participar! (Resultado em 30s)", view=view)
    await view.wait()
    if not view.choices:
        return await interaction.followup.send("☹️ Ninguém participou do jogo.")
    ganhador_num = random.randint(1, 3)
    ganhadores = [u for u, n in view.choices.items() if n == ganhador_num]
    if ganhadores:
        vencedor = random.choice(ganhadores)
        conn = sqlite3.connect('the_boys_bot.db')
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + 150 WHERE discord_id = ?", (vencedor.id,))
        conn.commit()
        conn.close()
        await interaction.followup.send(f"🎰 O número sorteado foi **{ganhador_num}**! O grande vencedor é {vencedor.mention} (+ $150)!")
    else:
        await interaction.followup.send(f"🎰 O número sorteado foi **{ganhador_num}**, mas ninguém escolheu ele!")

@bot.tree.command(name="presentemisterioso", description="Comando diário para ganhar prêmios aleatórios.")
async def presentemisterioso(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = get_user_db(user_id)
    now = datetime.datetime.now()
    if user_data[7]: # last_mystery
        last = datetime.datetime.fromisoformat(user_data[7])
        if (now - last).days < 1:
            return await interaction.response.send_message("⌛ Você já resgatou seu presente hoje!", ephemeral=True)
    
    premios = ["moedas", "carta_normal", "carta_especial", "moldura"]
    premio = random.choice(premios)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    msg = ""
    if premio == "moedas":
        valor = random.randint(10, 500)
        c.execute("UPDATE users SET balance = balance + ? WHERE discord_id = ?", (valor, user_id))
        msg = f"🎁 Você ganhou **${valor}** moedas!"
    elif premio == "carta_normal":
        c.execute("SELECT id, name FROM cards WHERE category = 'Normal' ORDER BY RANDOM() LIMIT 1")
        card = c.fetchone()
        if card:
            c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (user_id, card[0]))
            msg = f"🎁 Você ganhou a carta **{card[1]}**!"
    else:
        # Simplificação para outros prêmios
        valor = 100
        c.execute("UPDATE users SET balance = balance + ? WHERE discord_id = ?", (valor, user_id))
        msg = f"🎁 Você ganhou **$100** moedas!"
        
    c.execute("UPDATE users SET last_mystery = ? WHERE discord_id = ?", (now.isoformat(), user_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(msg)

@bot.tree.command(name="abraçar", description="Dê um abraço em alguém.")
async def abraçar(interaction: discord.Interaction, membro: discord.Member):
    await interaction.response.send_message(f"🫂 {interaction.user.mention} deu um abraço caloroso em {membro.mention}!")

@bot.tree.command(name="roubarlanche", description="Tente roubar o lanche de alguém.")
async def roubarlanche(interaction: discord.Interaction, membro: Optional[discord.Member] = None):
    alvo = membro.name if membro else "alguém"
    await interaction.response.send_message(f"🥪 {interaction.user.mention} sorrateiramente roubou o lanche de {alvo}!")

@bot.tree.command(name="add_shopping", description="[ADMIN] Adiciona um item na loja.")
async def add_shopping(interaction: discord.Interaction, tipo: str, item_id: str, nome: str, preco: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO shop (item_type, item_id, name, price) VALUES (?, ?, ?, ?)", (tipo, item_id, nome, preco))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🛒 Item **{nome}** adicionado à loja!")

@bot.tree.command(name="bônus", description="[ADMIN] Dá moedas para um jogador.")
async def bônus(interaction: discord.Interaction, membro: discord.Member, quantia: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE discord_id = ?", (quantia, membro.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"💸 **{quantia}** moedas foram adicionadas à conta de {membro.name}!")

@bot.tree.command(name="claim", description="[ADMIN] Dá uma carta para um jogador.")
async def claim(interaction: discord.Interaction, membro: discord.Member, codigo_carta: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (membro.id, codigo_carta))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🎁 Carta #{codigo_carta} adicionada ao inventário de {membro.name}!")

@bot.tree.command(name="criar_duo", description="[ADMIN] Cria uma carta de duo/casal.")
async def criar_duo(interaction: discord.Interaction, carta_a: int, carta_b: int, nome_duo: str, url_foto: str, categoria: str):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    # Criar a carta de resultado
    c.execute("INSERT INTO cards (name, category, tag, image_url) VALUES (?, ?, 'Duo', ?)", (nome_duo, categoria, url_foto))
    result_id = c.lastrowid
    # Criar a receita
    c.execute("INSERT INTO recipes (card_a_id, card_b_id, result_card_id) VALUES (?, ?, ?)", (carta_a, carta_b, result_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"💎 Duo **{nome_duo}** criado com sucesso! (ID #{result_id})")

@bot.tree.command(name="familia", description="Forme uma família com suas cartas (use códigos separados por vírgula).")
async def familia(interaction: discord.Interaction, codigos: str):
    user_id = interaction.user.id
    # Salvar no banco de dados (usaremos a coluna 'bio' ou uma nova para simplificar, mas aqui vamos simular via tag)
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    # Limpar família anterior
    c.execute("UPDATE inventory SET is_family = 0 WHERE user_id = ?", (user_id,))
    
    list_ids = [int(i.strip()) for i in codigos.split(',')]
    for cid in list_ids:
        c.execute("UPDATE inventory SET is_family = 1 WHERE user_id = ? AND card_id = ?", (user_id, cid))
    
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"👨‍👩‍👧‍👦 Família formada com as cartas: {codigos}!")

@bot.tree.command(name="agencia", description="Veja seu inventário de cartas.")
@app_commands.choices(filtro=[app_commands.Choice(name="Família", value="family")])
async def agencia(interaction: discord.Interaction, categoria: Optional[str] = None, time: Optional[str] = None, filtro: Optional[str] = None):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    query = '''SELECT cards.id, cards.name, inventory.amount, inventory.level, cards.tag 
               FROM inventory 
               JOIN cards ON inventory.card_id = cards.id 
               WHERE inventory.user_id = ?'''
    params = [user_id]
    
    if filtro == "family":
        query += " AND inventory.is_family = 1"
    if categoria:
        query += " AND cards.category = ?"
        params.append(categoria)
    if time:
        query += " AND cards.tag = ?"
        params.append(time)
    
    c.execute(query, tuple(params))
    items = c.fetchall()
    conn.close()
    
    if not items:
        return await interaction.response.send_message("📂 Sua agência está vazia!", ephemeral=True)
    
    level_map = {0: "", 1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "👑"}
    desc = "\n".join([f"`#{i[0]}` **{i[1]}** {level_map[i[3]]} — x{i[2]} ({i[4]})" for i in items])
    embed = discord.Embed(title=f"📂 Agência de {interaction.user.name}", description=desc[:4000], color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="time", description="Escolha sua facção.")
@app_commands.choices(tag=[app_commands.Choice(name=t, value=t) for t in ["Nova Ordem", "Ascendentes", "Vigilantes", "Esquadrão Solar", "Idols", "NPCs", "Civis"]])
async def time(interaction: discord.Interaction, tag: app_commands.Choice[str]):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET team = ? WHERE discord_id = ?", (tag.value, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Time definido: **{tag.value}**")

@bot.tree.command(name="teamo", description="Define sua carta favorita.")
async def teamo(interaction: discord.Interaction, codigo: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, codigo))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message("❌ Você não possui esta carta!", ephemeral=True)
    c.execute("UPDATE users SET favorite_card_id = ? WHERE discord_id = ?", (codigo, user_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"❤️ Favorito definido!")

@bot.tree.command(name="executar", description="Descarta uma carta do seu inventário.")
async def executar(interaction: discord.Interaction, codigo: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT id, amount FROM inventory WHERE user_id = ? AND card_id = ? LIMIT 1", (user_id, codigo))
    item = c.fetchone()
    if not item:
        conn.close()
        return await interaction.response.send_message("❌ Carta não encontrada!", ephemeral=True)
    
    if item[1] > 1:
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE id = ?", (item[0],))
    else:
        c.execute("DELETE FROM inventory WHERE id = ?", (item[0],))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"💀 Carta #{codigo} executada com sucesso.")

@bot.tree.command(name="chutar", description="Chuta um usuário.")
async def chutar(interaction: discord.Interaction, membro: discord.Member):
    await interaction.response.send_message(f"👟 {interaction.user.mention} deu um chute em {membro.mention}!")

@bot.tree.command(name="editar_carta", description="[ADMIN] Edita uma carta existente.")
async def editar_carta(interaction: discord.Interaction, codigo: int, nome: Optional[str] = None, url: Optional[str] = None):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    if nome: c.execute("UPDATE cards SET name = ? WHERE id = ?", (nome, codigo))
    if url: c.execute("UPDATE cards SET image_url = ? WHERE id = ?", (url, codigo))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Carta #{codigo} editada!")

@bot.tree.command(name="add_carta", description="[ADMIN] Adiciona uma carta comum ao sistema.")
@app_commands.choices(tag=[app_commands.Choice(name=t, value=t) for t in ["Nova Ordem", "Ascendentes", "Vigilantes", "Esquadrão Solar", "Idols", "NPCs", "Civis"]])
async def add_carta(interaction: discord.Interaction, nome: str, tag: app_commands.Choice[str], url: str):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO cards (name, category, tag, image_url) VALUES (?, 'Normal', ?, ?)", (nome, tag.value, url))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Carta **{nome}** adicionada ao time **{tag.value}**!")

@bot.tree.command(name="rem_carta", description="[ADMIN] Remove uma carta do sistema.")
async def rem_carta(interaction: discord.Interaction, codigo: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM cards WHERE id = ?", (codigo,))
    c.execute("DELETE FROM inventory WHERE card_id = ?", (codigo,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ Carta #{codigo} removida de todo o sistema.")

@bot.tree.command(name="rem_shopping", description="[ADMIN] Remove um item da loja.")
async def rem_shopping(interaction: discord.Interaction, item_id: str):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM shop WHERE item_id = ?", (item_id,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ Item {item_id} removido da loja.")

@bot.tree.command(name="add_c_comemorativa", description="[ADMIN] Adiciona uma carta comemorativa.")
async def add_c_comemorativa(interaction: discord.Interaction, codigo: int, nome: str, url: str):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cards (id, name, category, tag, image_url) VALUES (?, ?, 'Comemorativa', 'Comemorativa', ?)", (codigo, nome, url))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🎉 Carta Comemorativa **{nome}** (ID #{codigo}) adicionada!")



@bot.tree.command(name="add_c_especial", description="[ADMIN] Adiciona carta especial.")
async def add_c_especial(interaction: discord.Interaction, nome: str, url: str):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO cards (name, category, tag, image_url) VALUES (?, 'Especial', 'Especial', ?)", (nome, url))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🌟 Carta Especial **{nome}** adicionada!")

@bot.tree.command(name="add_moldura", description="[ADMIN] Adiciona uma moldura.")
async def add_moldura(interaction: discord.Interaction, codigo: int, nome: str, url: str, preco: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO frames (id, name, image_url) VALUES (?, ?, ?)", (codigo, nome, url))
    c.execute("INSERT INTO shop (item_type, item_id, name, price) VALUES ('frame', ?, ?, ?)", (str(codigo), nome, preco))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🖼️ Moldura **{nome}** adicionada!")

@bot.tree.command(name="combinar", description="Combine duas cartas para formar um Duo/Casal.")
async def combinar(interaction: discord.Interaction, carta_a: int, carta_b: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT result_card_id FROM recipes WHERE (card_a_id = ? AND card_b_id = ?) OR (card_a_id = ? AND card_b_id = ?)", (carta_a, carta_b, carta_b, carta_a))
    recipe = c.fetchone()
    if not recipe:
        conn.close()
        return await interaction.response.send_message("❌ Essas cartas não formam um Duo!", ephemeral=True)
    c.execute("SELECT amount FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, carta_a))
    inv_a = c.fetchone()
    c.execute("SELECT amount FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, carta_b))
    inv_b = c.fetchone()
    if not inv_a or not inv_b:
        conn.close()
        return await interaction.response.send_message("❌ Você não possui as cartas necessárias!", ephemeral=True)
    c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND card_id = ?", (user_id, carta_a))
    c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND card_id = ?", (user_id, carta_b))
    c.execute("INSERT INTO inventory (user_id, card_id, amount, level) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, level) DO UPDATE SET amount = amount + 1", (user_id, recipe[0]))
    c.execute("DELETE FROM inventory WHERE amount <= 0")
    c.execute("SELECT name FROM cards WHERE id = ?", (recipe[0],))
    duo_name = c.fetchone()[0]
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✨ **Fusão Completa!** Você obteve a carta Duo: **{duo_name}**!")

@bot.command()
@commands.has_permissions(administrator=True)
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("✅ Comandos Slash sincronizados com sucesso!")

@bot.event
async def on_ready():
    print(f'Vought International Bot Online: {bot.user}')

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Erro: DISCORD_TOKEN não encontrado.")
