import discord
from discord.ext import commands
import random
import os
import asyncio
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Configurar intents y bot
intents = discord.Intents.default()
intents.message_content = True
game_bot = commands.Bot(command_prefix="!town ", intents=intents)

# Variables globales del juego
game_active = False
participants = []
player_limit = 0
character_types = ["Impostor", "Villager", "Medic", "Sheriff"]
player_roles = {}  

# Estados del juego
current_phase = "daylight"  
impostor_votes = {}  
village_votes = {}  
eliminated_players = []

@game_bot.event
async def on_ready():
    print(f'✅ Bot iniciado como {game_bot.user}')
    await game_bot.change_presence(activity=discord.Game(name="!town help"))

@game_bot.command(name="help")
async def show_help(ctx):
    """Muestra la lista de comandos disponibles"""
    help_text = """
    **Comandos de Town Game:**
    `!town start <número>` - Inicia una nueva partida para el número especificado de jugadores
    `!town join` - Únete a la partida actual
    `!town reset` - Reinicia la partida
    `!town night` - Cambia a la fase nocturna
    `!town morning` - Cambia a la fase diurna
    `!town eliminate` - Elimina al jugador más votado
    `!town vote @jugador` - Vota para eliminar a un jugador durante el día
    `!town target @jugador` - (Solo impostores) Selecciona objetivo durante la noche
    """
    await ctx.send(help_text)

@game_bot.command(name="start")
async def start_game(ctx, player_count: int):
    global game_active, participants, player_limit

    if game_active:
        await ctx.send("Ya hay una partida en curso. Usa `!town reset` para empezar de nuevo.")
        return
    
    if player_count < 4:
        await ctx.send("Necesitas al menos 4 jugadores para iniciar una partida.")
        return

    game_active = True
    player_limit = player_count
    participants.append(ctx.author)

    await ctx.send(f"¡Partida creada por {ctx.author.mention}! Se necesitan {player_limit} jugadores. Usa `!town join` para participar.")

@game_bot.command(name="join")
async def join_game(ctx):
    global participants

    if not game_active:
        await ctx.send("No hay una partida activa. Usa `!town start <número>` para iniciar una.")
        return

    if ctx.author in participants:
        await ctx.send(f"{ctx.author.mention}, ya estás en la partida.")
        return

    participants.append(ctx.author)
    await ctx.send(f"{ctx.author.mention} se ha unido a la partida. ({len(participants)}/{player_limit})")

    if len(participants) == player_limit:
        await distribute_roles(ctx)

async def distribute_roles(ctx):
    global game_active, participants, player_roles, current_phase

    random.shuffle(participants)
    
    # Calculamos el número de impostores basado en el total de jugadores
    impostor_count = max(1, len(participants) // 4)
    
    # Asignamos roles
    roles_to_assign = (["Impostor"] * impostor_count) + (["Villager"] * (len(participants) - impostor_count - 2)) + ["Medic", "Sheriff"]
    random.shuffle(roles_to_assign)

    for i, player in enumerate(participants):
        player_roles[player] = roles_to_assign[i]
        try:
            await player.send(f"Tu rol en la partida es: **{roles_to_assign[i]}**")
            
            # Enviar instrucciones específicas según el rol
            if roles_to_assign[i] == "Impostor":
                await player.send("Tu objetivo es eliminar a los aldeanos sin ser descubierto. Usa `!town target @jugador` durante la noche.")
            elif roles_to_assign[i] == "Medic":
                await player.send("Puedes proteger a un jugador cada noche. Usa `!town protect @jugador` durante la noche.")
            elif roles_to_assign[i] == "Sheriff":
                await player.send("Puedes investigar a un jugador cada noche. Usa `!town investigate @jugador` durante la noche.")
            else:
                await player.send("Tu objetivo es identificar y eliminar a los impostores. Usa `!town vote @jugador` durante el día.")
                
        except discord.Forbidden:
            await ctx.send(f"No pude enviar mensaje privado a {player.mention}. Revisa tus ajustes de privacidad.")
    
    # Crear canal privado para impostores
    guild = ctx.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        game_bot.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    
    impostors = [player for player, role in player_roles.items() if role == "Impostor"]
    for impostor in impostors:
        overwrites[impostor] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    secret_channel = await guild.create_text_channel("impostor-hideout", overwrites=overwrites)
    
    # Enviar mensaje a los impostores en su canal
    if impostors:
        impostor_mentions = ", ".join([imp.mention for imp in impostors])
        await secret_channel.send(f"¡Bienvenidos impostores! {impostor_mentions}\nCoordinen sus acciones aquí durante la noche.")
    
    current_phase = "daylight"
    await ctx.send("¡Todos los roles han sido asignados en privado! La partida comienza en fase diurna.")

@game_bot.command(name="reset")
async def reset_game(ctx):
    global game_active, participants, player_limit, current_phase, impostor_votes, player_roles, village_votes, eliminated_players

    if not game_active:
        await ctx.send("No hay ninguna partida activa para reiniciar.")
        return

    # Intentar eliminar el canal de impostores si existe
    guild = ctx.guild
    for channel in guild.channels:
        if channel.name == "impostor-hideout":
            try:
                await channel.delete()
                break
            except discord.Forbidden:
                await ctx.send("No pude eliminar el canal de impostores. Asegúrate de que tengo permisos suficientes.")

    game_active = False
    participants = []
    player_limit = 0
    current_phase = "daylight"
    impostor_votes.clear()
    player_roles.clear()
    village_votes.clear()
    eliminated_players = []
    
    await ctx.send("La partida ha sido reiniciada. Usa `!town start <número>` para iniciar una nueva.")

@game_bot.command(name="night")
async def night_phase(ctx):
    global current_phase, impostor_votes

    if not game_active:
        await ctx.send("No hay ninguna partida activa.")
        return

    if current_phase == "night":
        await ctx.send("🌙 Ya estamos en la fase nocturna.")
        return

    current_phase = "night"
    impostor_votes.clear()
    await ctx.send("🌙 La noche ha caído. Los impostores pueden seleccionar a sus objetivos.")
    
    # Enviar mensaje al canal de impostores
    for channel in ctx.guild.channels:
        if channel.name == "impostor-hideout":
            await channel.send("Es hora de actuar. Usen `!town target @jugador` para seleccionar a su víctima.")
            break

@game_bot.command(name="target")
async def target_player(ctx, victim: discord.Member):
    global impostor_votes, current_phase, player_roles

    # Verificar si el comando se usó en el canal correcto
    if ctx.channel.name != "impostor-hideout":
        try:
            await ctx.message.delete()  # Eliminar el mensaje para mantener el secreto
            await ctx.author.send("❌ Solo puedes usar este comando en el canal secreto de impostores.")
        except:
            pass
        return

    # Verificar si es la fase correcta
    if current_phase != "night":
        await ctx.send("❌ Solo puedes elegir objetivos durante la noche.")
        return

    # Verificar si el jugador es impostor
    if player_roles.get(ctx.author) != "Impostor":
        await ctx.send("❌ Solo los impostores pueden usar este comando.")
        return
    
    # Verificar si el objetivo es válido
    if victim not in participants or victim in eliminated_players:
        await ctx.send("❌ Ese jugador no está en la partida o ya ha sido eliminado.")
        return

    # Registrar el voto
    impostor_votes[ctx.author] = victim
    await ctx.send(f"☠️ Has votado por eliminar a {victim.mention}.")
    
    # Verificar si todos los impostores han votado
    impostors = [p for p, r in player_roles.items() if r == "Impostor" and p not in eliminated_players]
    if len(impostor_votes) == len(impostors):
        await ctx.send("Todos los impostores han votado. Esperen a que amanezca (`!town morning`).")

@game_bot.command(name="morning")
async def morning_phase(ctx):
    global current_phase, impostor_votes, participants, eliminated_players

    if not game_active:
        await ctx.send("No hay ninguna partida activa.")
        return

    if current_phase != "night":
        await ctx.send("🌞 Ya es de día.")
        return

    current_phase = "daylight"

    if not impostor_votes:
        await ctx.send("🌞 Amaneció, todos los jugadores sobrevivieron esta noche.")
        return

    # Contar votos y determinar la víctima
    vote_counts = {}
    for victim in impostor_votes.values():
        vote_counts[victim] = vote_counts.get(victim, 0) + 1
    
    # Encontrar la víctima con más votos
    max_votes = max(vote_counts.values())
    potential_victims = [v for v, c in vote_counts.items() if c == max_votes]
    
    # Si hay empate, seleccionar aleatoriamente
    final_victim = random.choice(potential_victims)
    
    # Eliminar a la víctima
    if final_victim in participants:
        eliminated_players.append(final_victim)
        role = player_roles.get(final_victim, "Desconocido")
        
        # Anunciar la eliminación
        await ctx.send(f"🌞 Amaneció... y encontramos el cuerpo de **{final_victim.mention}**. Era un **{role}**. ¡Los aldeanos están aterrorizados!")
        
        # Verificar si el juego ha terminado
        game_result = check_winner()
        if game_result:
            await ctx.send(game_result)
            await reset_game(ctx)
    else:
        await ctx.send("🌞 Amaneció, pero hubo un error al procesar la eliminación.")
    
    # Limpiar los votos
    impostor_votes.clear()

@game_bot.command(name="vote")
async def vote_player(ctx, suspect: discord.Member):
    """Fase de votación de aldeanos."""
    global current_phase, village_votes, participants, eliminated_players

    if not game_active:
        await ctx.send("No hay ninguna partida activa.")
        return

    if current_phase != "daylight":
        await ctx.send("🗳️ La votación solo ocurre durante el día.")
        return
    
    if ctx.author not in participants or ctx.author in eliminated_players:
        await ctx.send("❌ No estás participando en la partida o has sido eliminado.")
        return
    
    if suspect not in participants or suspect in eliminated_players:
        await ctx.send("❌ Ese jugador no está en la partida o ya ha sido eliminado.")
        return

    village_votes[ctx.author] = suspect
    await ctx.send(f"🗳️ {ctx.author.mention} ha votado por eliminar a {suspect.mention}.")
    
    # Verificar si todos los jugadores han votado
    active_players = [p for p in participants if p not in eliminated_players]
    if len(village_votes) >= len(active_players):
        await ctx.send("Todos los jugadores han votado. Usen `!town eliminate` para proceder con la eliminación.")

@game_bot.command(name="eliminate")
async def eliminate_player(ctx):
    """Elimina al jugador más votado y verifica si el juego termina."""
    global village_votes, current_phase, player_roles, participants, eliminated_players

    if not game_active:
        await ctx.send("No hay ninguna partida activa.")
        return

    if current_phase != "daylight":
        await ctx.send("🚨 La eliminación solo ocurre durante el día.")
        return
    
    if not village_votes:
        await ctx.send("🚨 No hay votos registrados para eliminar a nadie.")
        return

    # Contar votos
    vote_counts = {}
    for suspect in village_votes.values():
        vote_counts[suspect] = vote_counts.get(suspect, 0) + 1
    
    # Encontrar el jugador con más votos
    max_votes = max(vote_counts.values())
    potential_suspects = [s for s, c in vote_counts.items() if c == max_votes]
    
    # Si hay empate, seleccionar aleatoriamente
    final_suspect = random.choice(potential_suspects)
    
    # Eliminar al jugador
    eliminated_players.append(final_suspect)
    role = player_roles.get(final_suspect, "Desconocido")
    
    # Anunciar la eliminación
    await ctx.send(f"🚨 El pueblo ha decidido. {final_suspect.mention} ha sido eliminado. Era un **{role}**.")
    
    # Verificar si el juego termina
    game_result = check_winner()
    if game_result:
        await ctx.send(game_result)
        await reset_game(ctx)
    else:
        await ctx.send("🎭 La partida continúa... ¡Prepárense para la siguiente fase!")
    
    # Limpiar los votos
    village_votes.clear()

def check_winner():
    """Verifica si hay un ganador en la partida."""
    global participants, player_roles, eliminated_players
    
    # Contar jugadores activos por rol
    active_players = [p for p in participants if p not in eliminated_players]
    impostors_remaining = sum(1 for p in active_players if player_roles.get(p) == "Impostor")
    villagers_remaining = len(active_players) - impostors_remaining

    if impostors_remaining == 0:
        return "🎉 ¡Los aldeanos han eliminado a todos los impostores! ¡Victoria para el pueblo! 🏆"
    elif impostors_remaining >= villagers_remaining:
        return "💀 ¡Los impostores han tomado el control del pueblo! ¡Victoria para los impostores! 🏆"

    return None  # El juego continúa

# Implementar comandos adicionales para roles especiales
@game_bot.command(name="protect")
async def protect_player(ctx, target: discord.Member):
    """Permite al médico proteger a un jugador durante la noche."""
    global current_phase, player_roles, participants, eliminated_players
    
    # Verificar si el comando se usó en un mensaje privado
    if ctx.guild is not None:
        try:
            await ctx.message.delete()  # Eliminar el mensaje para mantener el secreto
            await ctx.author.send("❌ Este comando solo puede usarse en mensaje privado.")
        except:
            pass
        return
    
    if current_phase != "night":
        await ctx.send("❌ Solo puedes proteger jugadores durante la noche.")
        return
    
    if player_roles.get(ctx.author) != "Medic":
        await ctx.send("❌ Solo el médico puede usar este comando.")
        return
    
    if target not in participants or target in eliminated_players:
        await ctx.send("❌ Ese jugador no está en la partida o ya ha sido eliminado.")
        return
    
    # Implementar la lógica de protección (por ejemplo, anular votos contra este jugador)
    # Esta es una función que necesitaría más desarrollo
    await ctx.send(f"✅ Has decidido proteger a {target.mention} esta noche.")

@game_bot.command(name="investigate")
async def investigate_player(ctx, target: discord.Member):
    """Permite al sheriff investigar a un jugador durante la noche."""
    global current_phase, player_roles, participants, eliminated_players
    
    # Verificar si el comando se usó en un mensaje privado
    if ctx.guild is not None:
        try:
            await ctx.message.delete()  # Eliminar el mensaje para mantener el secreto
            await ctx.author.send("❌ Este comando solo puede usarse en mensaje privado.")
        except:
            pass
        return
    
    if current_phase != "night":
        await ctx.send("❌ Solo puedes investigar jugadores durante la noche.")
        return
    
    if player_roles.get(ctx.author) != "Sheriff":
        await ctx.send("❌ Solo el sheriff puede usar este comando.")
        return
    
    if target not in participants or target in eliminated_players:
        await ctx.send("❌ Ese jugador no está en la partida o ya ha sido eliminado.")
        return
    
    # Revelar si el jugador es impostor o no
    role = player_roles.get(target)
    is_impostor = "Impostor" if role == "Impostor" else "No es impostor"
    await ctx.send(f"🔍 Tu investigación revela que {target.mention} es: **{is_impostor}**.")

# Iniciar el bot
game_bot.run(TOKEN)