import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import datetime
import os
from dotenv import load_dotenv
from typing import Optional

# Carregar variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Configuração do Bot
class TheBoysBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Comandos sincronizados para {self.user}")

bot = TheBoysBot()

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Tabela de Usuários
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (discord_id INTEGER PRIMARY KEY, 
                  team TEXT, 
                  favorite_card_id INTEGER,
                  last_drop TEXT)''')
    
    # Tabela de Cartas
    c.execute('''CREATE TABLE IF NOT EXISTS cards 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, 
                  category TEXT, 
                  tag TEXT, 
                  image_url TEXT)''')
    
    # Tabela de Inventário
    c.execute('''CREATE TABLE IF NOT EXISTS inventory 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id INTEGER, 
                  card_id INTEGER, 
                  amount INTEGER DEFAULT 1,
                  FOREIGN KEY(user_id) REFERENCES users(discord_id),
                  FOREIGN KEY(card_id) REFERENCES cards(id))''')
    
    # Inserir cartas iniciais (The Boys theme)
    c.execute("SELECT COUNT(*) FROM cards")
    if c.fetchone()[0] == 0:
        initial_cards = [
            ('Billy Butcher', 'Humanos', 'Vigilantes', 'https://i.imgur.com/rXp8QWz.jpeg'),
            ('Homelander', 'Supers', 'Nova Ordem', 'https://i.imgur.com/vH9Z9Xy.jpeg'),
            ('Starlight', 'Supers', 'Esquadrão Solar', 'https://i.imgur.com/u7L5Xz8.jpeg'),
            ('Hughie Campbell', 'Humanos', 'Vigilantes', 'https://i.imgur.com/9m5yW7A.jpeg')
        ]
        c.executemany("INSERT INTO cards (name, category, tag, image_url) VALUES (?, ?, ?, ?)", initial_cards)
    
    conn.commit()
    conn.close()

init_db()

# --- FUNÇÕES AUXILIARES ---
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

def get_ranking_pos(user_id):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute('''SELECT user_id, SUM(amount) as total FROM inventory 
                 GROUP BY user_id ORDER BY total DESC''')
    ranking = c.fetchall()
    conn.close()
    for idx, row in enumerate(ranking):
        if row[0] == user_id:
            return idx + 1
    return "N/A"

# --- COMANDOS PÚBLICOS ---

@bot.tree.command(name="recrutar", description="Recrute um novo membro para sua equipe! (A cada 10 min)")
async def recrutar(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = get_user_db(user_id)
    
    now = datetime.datetime.now()
    if user_data[3]: # last_drop
        last_drop = datetime.datetime.fromisoformat(user_data[3])
        diff = (now - last_drop).total_seconds()
        if diff < 600:
            wait_time = int((600 - diff) / 60)
            return await interaction.response.send_message(f"🚫 Você precisa esperar {wait_time} minutos para recrutar novamente.", ephemeral=True)

    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM cards ORDER BY RANDOM() LIMIT 1")
    card = c.fetchone()
    
    if not card:
        conn.close()
        return await interaction.response.send_message("Nenhuma carta disponível no sistema ainda!", ephemeral=True)
    
    # Adicionar ao inventário
    c.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, card[0]))
    inv_item = c.fetchone()
    if inv_item:
        c.execute("UPDATE inventory SET amount = amount + 1 WHERE id = ?", (inv_item[0],))
    else:
        c.execute("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (user_id, card[0]))
    
    c.execute("UPDATE users SET last_drop = ? WHERE discord_id = ?", (now.isoformat(), user_id))
    conn.commit()
    conn.close()
    
    embed = discord.Embed(title="🎖️ Novo Recruta Encontrado!", color=discord.Color.red())
    embed.add_field(name="Nome", value=card[1], inline=True)
    embed.add_field(name="Categoria", value=card[2], inline=True)
    embed.add_field(name="Tag/Time", value=card[3], inline=True)
    embed.set_image(url=card[4])
    embed.set_footer(text=f"ID da Carta: {card[0]}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="agencia", description="Veja todos os seus recrutas na Agência.")
async def agencia(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute('''SELECT cards.id, cards.name, cards.tag, inventory.amount 
                 FROM inventory 
                 JOIN cards ON inventory.card_id = cards.id 
                 WHERE inventory.user_id = ?''', (user_id,))
    items = c.fetchall()
    conn.close()
    
    if not items:
        return await interaction.response.send_message("Sua agência está vazia. Use `/recrutar`!", ephemeral=True)
    
    desc = "\n".join([f"`#{item[0]}` **{item[1]}** [{item[2]}] - x{item[3]}" for item in items])
    embed = discord.Embed(title=f"🏢 Agência de {interaction.user.name}", description=desc, color=discord.Color.dark_grey())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="carreira", description="Veja seu perfil de carreira.")
async def carreira(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = get_user_db(user_id)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM inventory WHERE user_id = ?", (user_id,))
    total_cards = c.fetchone()[0] or 0
    
    fav_card = None
    if user_data[2]: # favorite_card_id
        c.execute("SELECT name, image_url FROM cards WHERE id = ?", (user_data[2],))
        fav_card = c.fetchone()
    conn.close()
    
    ranking = get_ranking_pos(user_id)
    
    embed = discord.Embed(title=f"📁 Dossier: {interaction.user.name}", color=discord.Color.blue())
    embed.add_field(name="Time", value=user_data[1] or "Nenhum", inline=True)
    embed.add_field(name="Total de Cartas", value=str(total_cards), inline=True)
    embed.add_field(name="Ranking", value=f"#{ranking}", inline=True)
    
    if fav_card:
        embed.add_field(name="⭐ Herói Favorito", value=fav_card[0], inline=False)
        embed.set_thumbnail(url=fav_card[1])
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="time", description="Escolha sua facção.")
@app_commands.choices(tag=[
    app_commands.Choice(name="Nova Ordem", value="Nova Ordem"),
    app_commands.Choice(name="Ascendentes", value="Ascendentes"),
    app_commands.Choice(name="Vigilantes", value="Vigilantes"),
    app_commands.Choice(name="Esquadrão Solar", value="Esquadrão Solar"),
    app_commands.Choice(name="Civis", value="Civis"),
    app_commands.Choice(name="Idols", value="Idols"),
    app_commands.Choice(name="NPCs", value="NPCs"),
])
async def time(interaction: discord.Interaction, tag: app_commands.Choice[str]):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET team = ? WHERE discord_id = ?", (tag.value, user_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Você agora faz parte dos **{tag.value}**!")

@bot.tree.command(name="meuheroi", description="Escolha sua carta favorita pelo código.")
async def meuheroi(interaction: discord.Interaction, codigo: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Verificar se o usuário tem a carta
    c.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, codigo))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message("❌ Você não possui essa carta no seu inventário!", ephemeral=True)
    
    c.execute("UPDATE users SET favorite_card_id = ? WHERE discord_id = ?", (codigo, user_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"⭐ Carta #{codigo} definida como sua favorita!")

# --- COMANDOS ADMIN ---

@bot.tree.command(name="add_carta", description="[ADMIN] Adicionar nova carta.")
@app_commands.choices(categoria=[
    app_commands.Choice(name="Humanos", value="Humanos"),
    app_commands.Choice(name="Supers", value="Supers"),
], tag=[
    app_commands.Choice(name="Nova Ordem", value="Nova Ordem"),
    app_commands.Choice(name="Ascendentes", value="Ascendentes"),
    app_commands.Choice(name="Vigilantes", value="Vigilantes"),
    app_commands.Choice(name="Esquadrão Solar", value="Esquadrão Solar"),
    app_commands.Choice(name="Civis", value="Civis"),
    app_commands.Choice(name="Idols", value="Idols"),
    app_commands.Choice(name="NPCs", value="NPCs"),
])
async def add_carta(interaction: discord.Interaction, nome: str, categoria: str, tag: str, url_imagem: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Apenas administradores podem usar isso!", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO cards (name, category, tag, image_url) VALUES (?, ?, ?, ?)", (nome, categoria, tag, url_imagem))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Carta **{nome}** adicionada com sucesso!")

@bot.tree.command(name="remover_carta", description="[ADMIN] Remover uma carta pelo ID.")
async def remover_carta(interaction: discord.Interaction, codigo: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Apenas administradores podem usar isso!", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM cards WHERE id = ?", (codigo,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ Carta #{codigo} removida do sistema.")

@bot.event
async def on_ready():
    print(f'Vought International Bot Online: {bot.user}')

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Erro: DISCORD_TOKEN não encontrado.")
