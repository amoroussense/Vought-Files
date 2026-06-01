import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import datetime
import os
from dotenv import load_dotenv
from typing import Optional, List

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
                  last_drop TEXT,
                  custom_name TEXT,
                  custom_image TEXT,
                  wins INTEGER DEFAULT 0)''')
    
    # Tabela de Cartas
    c.execute('''CREATE TABLE IF NOT EXISTS cards 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, 
                  category TEXT, 
                  tag TEXT, 
                  image_url TEXT,
                  evolved_image_url TEXT)''')
    
    # Tabela de Inventário (Adicionado card_wins para rastrear vitórias daquela carta específica do usuário)
    c.execute('''CREATE TABLE IF NOT EXISTS inventory 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id INTEGER, 
                  card_id INTEGER, 
                  amount INTEGER DEFAULT 1,
                  is_evolved INTEGER DEFAULT 0,
                  card_wins INTEGER DEFAULT 0,
                  UNIQUE(user_id, card_id, is_evolved),
                  FOREIGN KEY(user_id) REFERENCES users(discord_id),
                  FOREIGN KEY(card_id) REFERENCES cards(id))''')
    
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
    c.execute("INSERT INTO inventory (user_id, card_id, amount, is_evolved) VALUES (?, ?, 1, 0) ON CONFLICT(user_id, card_id, is_evolved) DO UPDATE SET amount = amount + 1", (user_id, card[0]))
    c.execute("UPDATE users SET last_drop = ? WHERE discord_id = ?", (now.isoformat(), user_id))
    conn.commit()
    conn.close()
    
    embed = discord.Embed(title="🎖️ Novo Recruta Encontrado!", color=discord.Color.red())
    embed.add_field(name="Nome", value=card[1], inline=True)
    embed.add_field(name="Categoria", value=card[2], inline=True)
    embed.add_field(name="Time", value=card[3], inline=True)
    embed.set_image(url=card[4])
    embed.set_footer(text=f"ID da Carta: {card[0]}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="agencia", description="Veja todos os seus recrutas na Agência.")
async def agencia(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute('''SELECT cards.id, cards.name, cards.tag, inventory.amount, inventory.is_evolved 
                 FROM inventory 
                 JOIN cards ON inventory.card_id = cards.id 
                 WHERE inventory.user_id = ?''', (user_id,))
    items = c.fetchall()
    conn.close()
    
    if not items:
        return await interaction.response.send_message("Sua agência está vazia. Use `/recrutar`!", ephemeral=True)
    
    desc = "\n".join([f"`#{item[0]}` **{item[1]}** {'👑' if item[4] else ''} [{item[2]}] - x{item[3]}" for item in items])
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
        c.execute("SELECT name, image_url, evolved_image_url FROM cards WHERE id = ?", (user_data[2],))
        fav_card = c.fetchone()
        c.execute("SELECT is_evolved FROM inventory WHERE user_id = ? AND card_id = ? AND is_evolved = 1", (user_id, user_data[2]))
        is_fav_evolved = c.fetchone()
    conn.close()
    
    ranking = get_ranking_pos(user_id)
    display_name = user_data[4] or interaction.user.name
    
    embed = discord.Embed(title=f"📁 Dossier: {display_name}", color=discord.Color.blue())
    embed.add_field(name="Time", value=user_data[1] or "Nenhum", inline=True)
    embed.add_field(name="Total de Cartas", value=str(total_cards), inline=True)
    embed.add_field(name="Ranking", value=f"#{ranking}", inline=True)
    embed.add_field(name="🏅 Batalhas Ganhas", value=str(user_data[6] or 0), inline=True)
    
    if fav_card:
        name_display = f"{fav_card[0]} 👑" if (is_fav_evolved and fav_card[2]) else fav_card[0]
        img_display = fav_card[2] if (is_fav_evolved and fav_card[2]) else fav_card[1]
        embed.add_field(name="⭐ Herói Favorito", value=name_display, inline=False)
        embed.set_thumbnail(url=img_display)
    
    if user_data[5]: # custom_image
        embed.set_image(url=user_data[5])
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="admirar", description="Veja detalhes de uma carta específica.")
async def admirar(interaction: discord.Interaction, codigo: int):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Buscar dados da carta
    c.execute("SELECT name, category, tag, image_url, evolved_image_url FROM cards WHERE id = ?", (codigo,))
    card = c.fetchone()
    
    if not card:
        conn.close()
        return await interaction.response.send_message("❌ Carta não encontrada!", ephemeral=True)
    
    # Verificar se o usuário possui a carta
    c.execute("SELECT amount, card_wins, is_evolved FROM inventory WHERE user_id = ? AND card_id = ?", (interaction.user.id, codigo))
    inv_data = c.fetchall() # Pode ter versão normal e evoluída
    conn.close()
    
    embed = discord.Embed(title=f"🔍 Admirando: {card[0]}", color=discord.Color.purple())
    embed.add_field(name="Categoria", value=card[1], inline=True)
    embed.add_field(name="Time", value=card[2], inline=True)
    
    if inv_data:
        total_qnt = sum(item[0] for item in inv_data)
        total_wins = sum(item[1] for item in inv_data)
        has_evolved = any(item[2] == 1 for item in inv_data)
        
        status_text = f"Você possui **{total_qnt}** unidades.\nVitórias com esta carta: **{total_wins}** 🏅"
        if has_evolved:
            status_text += "\n✨ Você possui a versão **Coroada**!"
        embed.add_field(name="Seu Status", value=status_text, inline=False)
        
        # Mostrar imagem evoluída se ele tiver a evoluída, senão a normal
        img_to_show = card[4] if (has_evolved and card[4]) else card[3]
        embed.set_image(url=img_to_show)
    else:
        embed.add_field(name="Seu Status", value="Você ainda não recrutou este membro.", inline=False)
        embed.set_image(url=card[3])
    
    embed.set_footer(text=f"ID: #{codigo}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="upar", description="Evolua uma carta (Gasta 50 unidades da mesma carta).")
async def upar(interaction: discord.Interaction, codigo: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    c.execute("SELECT id, amount FROM inventory WHERE user_id = ? AND card_id = ? AND is_evolved = 0", (user_id, codigo))
    inv_item = c.fetchone()
    
    if not inv_item or inv_item[1] < 50:
        conn.close()
        return await interaction.response.send_message("❌ Você precisa de pelo menos 50 unidades dessa carta para upar!", ephemeral=True)
    
    c.execute("SELECT name, evolved_image_url FROM cards WHERE id = ?", (codigo,))
    card_info = c.fetchone()
    if not card_info[1]:
        conn.close()
        return await interaction.response.send_message("❌ Esta carta ainda não possui uma versão 'Coroada' (GIF) disponível.", ephemeral=True)

    if inv_item[1] == 50:
        c.execute("DELETE FROM inventory WHERE id = ?", (inv_item[0],))
    else:
        c.execute("UPDATE inventory SET amount = amount - 50 WHERE id = ?", (inv_item[0],))
    
    c.execute("INSERT INTO inventory (user_id, card_id, amount, is_evolved) VALUES (?, ?, 1, 1) ON CONFLICT(user_id, card_id, is_evolved) DO UPDATE SET amount = amount + 1", (user_id, codigo))
    
    conn.commit()
    conn.close()
    
    embed = discord.Embed(title="👑 EVOLUÇÃO CONCLUÍDA!", description=f"Sua carta **{card_info[0]}** agora é uma versão Coroada!", color=discord.Color.gold())
    embed.set_image(url=card_info[1])
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="batalhar", description="Desafie alguém para uma batalha de cartas!")
async def batalhar(interaction: discord.Interaction, oponente: discord.Member, codigo_sua_carta: int):
    user_id = interaction.user.id
    if oponente.id == user_id:
        return await interaction.response.send_message("❌ Você não pode lutar contra si mesmo!", ephemeral=True)

    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT is_evolved FROM inventory WHERE user_id = ? AND card_id = ? AND amount > 0", (user_id, codigo_sua_carta))
    inv_item = c.fetchone()
    if not inv_item:
        conn.close()
        return await interaction.response.send_message("❌ Você não possui essa carta!", ephemeral=True)
    is_evolved = inv_item[0]
    conn.close()

    view = ConfirmInteraction(oponente, interaction.user)
    await interaction.response.send_message(f"⚔️ {oponente.mention}, {interaction.user.mention} te desafiou para uma batalha usando a carta #{codigo_sua_carta}! Você aceita?", view=view)
    
    await view.wait()
    if view.value is True:
        vencedor = random.choice([interaction.user, oponente])
        perdedor = oponente if vencedor == interaction.user else interaction.user
        
        conn = sqlite3.connect('the_boys_bot.db')
        c = conn.cursor()
        # Atualizar vitórias do usuário
        c.execute("UPDATE users SET wins = wins + 1 WHERE discord_id = ?", (vencedor.id,))
        # Atualizar vitórias da CARTA (se o vencedor foi quem iniciou e usou a carta)
        if vencedor == interaction.user:
            c.execute("UPDATE inventory SET card_wins = card_wins + 1 WHERE user_id = ? AND card_id = ? AND is_evolved = ?", (user_id, codigo_sua_carta, is_evolved))
        
        conn.commit()
        conn.close()
        await interaction.followup.send(f"🏆 A batalha terminou! **{vencedor.name}** venceu o combate!")
    else:
        await interaction.followup.send(f"🏳️ O desafio foi recusado ou expirou.")

@bot.tree.command(name="trocar", description="Troque uma carta com outro membro.")
async def trocar(interaction: discord.Interaction, oponente: discord.Member, sua_carta_id: int, carta_dele_id: int):
    user_id = interaction.user.id
    if oponente.id == user_id:
        return await interaction.response.send_message("❌ Você não pode trocar consigo mesmo!", ephemeral=True)

    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND amount > 0", (user_id, sua_carta_id))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message(f"❌ Você não possui a carta #{sua_carta_id}!", ephemeral=True)
    
    c.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND amount > 0", (oponente.id, carta_dele_id))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message(f"❌ {oponente.name} não possui a carta #{carta_dele_id}!", ephemeral=True)
    conn.close()

    view = ConfirmInteraction(oponente, interaction.user)
    await interaction.response.send_message(f"🤝 {oponente.mention}, {interaction.user.mention} quer trocar a carta #{sua_carta_id} pela sua #{carta_dele_id}. Aceita?", view=view)
    
    await view.wait()
    if view.value is True:
        conn = sqlite3.connect('the_boys_bot.db')
        c = conn.cursor()
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND card_id = ?", (user_id, sua_carta_id))
        c.execute("INSERT INTO inventory (user_id, card_id, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, card_id, is_evolved) DO UPDATE SET amount = amount + 1", (user_id, carta_dele_id))
        c.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND card_id = ?", (oponente.id, carta_dele_id))
        c.execute("INSERT INTO inventory (user_id, card_id, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, card_id, is_evolved) DO UPDATE SET amount = amount + 1", (oponente.id, sua_carta_id))
        c.execute("DELETE FROM inventory WHERE amount <= 0")
        conn.commit()
        conn.close()
        await interaction.followup.send(f"✅ Troca realizada com sucesso!")
    else:
        await interaction.followup.send("❌ Troca cancelada.")

# --- DEMAIS COMANDOS (Customização, Admin, etc) ---

@bot.tree.command(name="disponiveis", description="Mostra todas as cartas do sistema.")
@app_commands.choices(categoria=[app_commands.Choice(name="Humanos", value="Humanos"), app_commands.Choice(name="Supers", value="Supers")])
async def disponiveis(interaction: discord.Interaction, categoria: Optional[str] = None, tag: Optional[str] = None):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    query = "SELECT id, name, category, tag FROM cards"
    params = []
    if categoria or tag:
        query += " WHERE"
        if categoria:
            query += " category = ?"
            params.append(categoria)
        if tag:
            if categoria: query += " AND"
            query += " tag = ?"
            params.append(tag)
    c.execute(query, tuple(params))
    cards = c.fetchall()
    conn.close()
    if not cards: return await interaction.response.send_message("Nada encontrado.", ephemeral=True)
    desc = "\n".join([f"`#{c[0]}` **{c[1]}** ({c[2]} - {c[3]})" for c in cards])
    await interaction.response.send_message(embed=discord.Embed(title="🗃️ Catálogo", description=desc[:4000], color=discord.Color.green()))

@bot.tree.command(name="setname", description="Mude seu nome no perfil.")
async def setname(interaction: discord.Interaction, nome: str):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET custom_name = ? WHERE discord_id = ?", (nome, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Nome alterado!")

@bot.tree.command(name="setimage", description="Defina imagem do perfil (link).")
async def setimage(interaction: discord.Interaction, url: str):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET custom_image = ? WHERE discord_id = ?", (url, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Imagem alterada!")

@bot.tree.command(name="time", description="Escolha sua facção.")
@app_commands.choices(tag=[app_commands.Choice(name=t, value=t) for t in ["Nova Ordem", "Ascendentes", "Vigilantes", "Esquadrão Solar", "Civis", "Idols", "NPCs"]])
async def time(interaction: discord.Interaction, tag: app_commands.Choice[str]):
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET team = ? WHERE discord_id = ?", (tag.value, interaction.user.id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Time definido: **{tag.value}**")

@bot.tree.command(name="meuheroi", description="Defina seu favorito.")
async def meuheroi(interaction: discord.Interaction, codigo: int):
    user_id = interaction.user.id
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, codigo))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message("❌ Você não tem essa carta!", ephemeral=True)
    c.execute("UPDATE users SET favorite_card_id = ? WHERE discord_id = ?", (codigo, user_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"⭐ Favorito definido!")

@bot.tree.command(name="setgif", description="[ADMIN] Definir GIF de evolução.")
async def setgif(interaction: discord.Interaction, codigo: int, url_gif: str):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("UPDATE cards SET evolved_image_url = ? WHERE id = ?", (url_gif, codigo))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ GIF definido para #{codigo}!")

@bot.tree.command(name="add_carta", description="[ADMIN] Add carta.")
async def add_carta(interaction: discord.Interaction, nome: str, categoria: str, tag: str, url_imagem: str, url_gif: Optional[str] = None):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO cards (name, category, tag, image_url, evolved_image_url) VALUES (?, ?, ?, ?, ?)", (nome, categoria, tag, url_imagem, url_gif))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Adicionada!")

@bot.tree.command(name="remover_carta", description="[ADMIN] Remove uma carta permanentemente do sistema.")
async def remover_carta(interaction: discord.Interaction, codigo: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Apenas administradores podem remover cartas!", ephemeral=True)
    
    conn = sqlite3.connect('the_boys_bot.db')
    c = conn.cursor()
    
    # Verificar se a carta existe
    c.execute("SELECT name FROM cards WHERE id = ?", (codigo,))
    card = c.fetchone()
    if not card:
        conn.close()
        return await interaction.response.send_message(f"❌ Carta com ID #{codigo} não encontrada.", ephemeral=True)
    
    # Remover a carta e limpar inventários
    c.execute("DELETE FROM cards WHERE id = ?", (codigo,))
    c.execute("DELETE FROM inventory WHERE card_id = ?", (codigo,))
    
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ A carta **{card[0]}** (ID #{codigo}) foi removida do sistema e de todos os inventários.")

class ConfirmInteraction(discord.ui.View):
    def __init__(self, target, challenger):
        super().__init__(timeout=60)
        self.target, self.challenger, self.value = target, challenger, None
    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.green)
    async def accept(self, interaction, button):
        if interaction.user != self.target: return
        self.value = True
        self.stop()
        await interaction.response.defer()
    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.red)
    async def decline(self, interaction, button):
        if interaction.user != self.target: return
        self.value = False
        self.stop()
        await interaction.response.defer()

@bot.event
async def on_ready(): print(f'Online: {bot.user}')

if __name__ == "__main__": bot.run(TOKEN)
