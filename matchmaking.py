import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import itertools
import os
import logging
from datetime import datetime

from rating_system import new_team_ratings

# --- Configuration ---
PLAYERS_CSV_PATH = 'players.csv'
MATCHES_CSV_PATH = 'matches.csv'
DEFAULT_RATING = 1500
DEFAULT_DEVIATION = 350

# --- Helper Functions ---

def get_player_data():
    """Reads player data from the CSV, creating it if it doesn't exist."""
    if not os.path.exists(PLAYERS_CSV_PATH):
        df = pd.DataFrame(columns=['discord_id', 'display_name', 'rating', 'deviation'])
        df.to_csv(PLAYERS_CSV_PATH, index=False)
        return df
    # Explicitly set dtypes to prevent warnings when updating integer ratings with floats.
    return pd.read_csv(PLAYERS_CSV_PATH, dtype={
        'discord_id': int,
        'rating': float,
        'deviation': float
    })

def save_player_data(df):
    """Saves the player DataFrame to the CSV."""
    # Create a copy to ensure the in-memory DataFrame remains float for calculations
    df_to_save = df.copy()
    df_to_save[['rating', 'deviation']] = df_to_save[['rating', 'deviation']].round().astype(int)
    df_to_save.to_csv(PLAYERS_CSV_PATH, index=False)

def get_or_create_player(player_id: int, player_name: str):
    """
    Retrieves a player from the CSV by discord_id. If the player doesn't exist,
    creates a new entry with default values.
    """
    players_df = get_player_data()
    player = players_df[players_df['discord_id'] == player_id]

    if player.empty:
        new_player = pd.DataFrame([{
            'discord_id': player_id,
            'display_name': player_name,
            'rating': DEFAULT_RATING,
            'deviation': DEFAULT_DEVIATION
        }])
        players_df = pd.concat([players_df, new_player], ignore_index=True)
        save_player_data(players_df)
        logging.info(f"Created new player: {player_name} ({player_id})")
        return new_player.iloc[0]
    
    # Update display name if it has changed
    if player.iloc[0]['display_name'] != player_name:
        players_df.loc[players_df['discord_id'] == player_id, 'display_name'] = player_name
        save_player_data(players_df)

    return player.iloc[0]

def balance_teams(players: list):
    """
    Balances two teams of 5 from a list of 10 players to have the most similar average rating.
    """
    min_diff = float('inf')
    best_teams = ([], [])

    # Iterate through all combinations of 5 players for team 1
    for team1_tuple in itertools.combinations(players, 5):
        team1_list = list(team1_tuple)
        team2_list = [p for p in players if p not in team1_list]

        team1_avg_rating = sum(p['rating'] for p in team1_list) / 5
        team2_avg_rating = sum(p['rating'] for p in team2_list) / 5

        diff = abs(team1_avg_rating - team2_avg_rating)

        if diff < min_diff:
            min_diff = diff
            best_teams = (team1_list, team2_list)

    return best_teams[0], best_teams[1]

# --- UI Views ---

class CreateTeamsView(discord.ui.View):
    """View for creating and confirming teams."""
    def __init__(self, author_id: int, matchmaking_cog, team1: list, team2: list):
        super().__init__(timeout=900) # 15 minute timeout
        self.author_id = author_id
        self.cog = matchmaking_cog
        self.team1 = team1
        self.team2 = team2

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the command author can interact with this view
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who started this can modify the teams.", ephemeral=True)
            return False
        return True

    async def update_embed(self, interaction: discord.Interaction):
        """Helper to update the message embed with current team compositions."""
        embed = self.cog.create_team_embed(self.team1, self.team2)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Swap Players", style=discord.ButtonStyle.primary, emoji="🔁")
    async def swap_players(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Modals can't have select menus, so we switch to a dedicated view for swapping.
        swap_view = SwapPlayersView(self)
        await interaction.response.edit_message(view=swap_view)
        
    @discord.ui.button(label="Confirm Match", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        match_id = int(datetime.now().timestamp())
        self.cog.active_matches[interaction.channel_id] = {
            "match_id": match_id,
            "team1": self.team1,
            "team2": self.team2
        }
        
        # Clean up pending match
        if interaction.channel_id in self.cog.pending_matches:
            del self.cog.pending_matches[interaction.channel_id]

        # Use mentions here because the match is confirmed and players should be notified.
        use_mentions = not self.cog.silenced_mentions
        embed = self.cog.create_team_embed(self.team1, self.team2, use_mentions=use_mentions)
        embed.title = "⚔️ Match Confirmed! ⚔️"
        embed.set_footer(text=f"Match ID: {match_id}. Use /report_match to record the winner.")
        
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel_id in self.cog.pending_matches:
            del self.cog.pending_matches[interaction.channel_id]

        await interaction.response.edit_message(content="Match creation cancelled.", embed=None, view=None)
        self.stop()

class SwapPlayersView(discord.ui.View):
    """A view to handle swapping players between two teams."""
    def __init__(self, original_view: CreateTeamsView):
        super().__init__(timeout=300)
        self.original_view = original_view

        team1_options = [discord.SelectOption(label=p['display_name'], value=str(p['discord_id'])) for p in self.original_view.team1]
        team2_options = [discord.SelectOption(label=p['display_name'], value=str(p['discord_id'])) for p in self.original_view.team2]

        self.team1_select = discord.ui.Select(placeholder="Select player from Blue Team", options=team1_options, custom_id="swap_team1")
        self.team2_select = discord.ui.Select(placeholder="Select player from Red Team", options=team2_options, custom_id="swap_team2")

        async def select_callback(interaction: discord.Interaction):
            # This callback's only job is to acknowledge the interaction to prevent "Interaction failed".
            await interaction.response.defer()

        self.team1_select.callback = select_callback
        self.team2_select.callback = select_callback
        self.add_item(self.team1_select)
        self.add_item(self.team2_select)

    @discord.ui.button(label="Confirm Swap", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_swap(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.team1_select.values or not self.team2_select.values:
            await interaction.response.send_message("You must select one player from each team to swap.", ephemeral=True)
            return

        p1_id = int(self.team1_select.values[0])
        p2_id = int(self.team2_select.values[0])

        # Find and swap the players in the original view's teams
        p1_data = next((p for p in self.original_view.team1 if p['discord_id'] == p1_id), None)
        p2_data = next((p for p in self.original_view.team2 if p['discord_id'] == p2_id), None)

        if p1_data and p2_data:
            self.original_view.team1.remove(p1_data)
            self.original_view.team2.remove(p2_data)
            self.original_view.team1.append(p2_data)
            self.original_view.team2.append(p1_data)

        # Edit the message to show the original view again with the updated teams
        embed = self.original_view.cog.create_team_embed(self.original_view.team1, self.original_view.team2, use_mentions=False)
        await interaction.response.edit_message(embed=embed, view=self.original_view)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_swap(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancels the swap and returns to the original team view."""
        embed = self.original_view.cog.create_team_embed(self.original_view.team1, self.original_view.team2, use_mentions=False)
        await interaction.response.edit_message(embed=embed, view=self.original_view)
        self.stop()

class LeaderboardView(discord.ui.View):
    """A view to handle paginated leaderboards."""
    def __init__(self, sorted_players_df: pd.DataFrame, author_id: int):
        super().__init__(timeout=300)
        self.players = sorted_players_df
        self.author_id = author_id
        self.current_page = 0
        self.players_per_page = 10
        self.total_pages = (len(self.players) - 1) // self.players_per_page + 1

        self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the command author can interact with this view
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who started the command can change pages.", ephemeral=True)
            return False
        return True

    def update_buttons(self):
        """Enables or disables buttons based on the current page."""
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page >= self.total_pages - 1

    def create_leaderboard_embed(self) -> discord.Embed:
        """Creates the embed for the current page of the leaderboard."""
        start_index = self.current_page * self.players_per_page
        end_index = start_index + self.players_per_page
        page_players = self.players.iloc[start_index:end_index]

        embed = discord.Embed(title="🏆 Rating Leaderboard 🏆", color=discord.Color.purple())
        
        leaderboard_entries = []
        for index, player in page_players.iterrows():
            # The rank is the player's overall position in the sorted DataFrame
            rank = index + 1
            name = player['display_name']
            rating = int(player['rating'])
            leaderboard_entries.append(f"**#{rank}** {name} - `{rating}`")

        embed.description = "\n".join(leaderboard_entries) if leaderboard_entries else "No players on this page."
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.total_pages}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        embed = self.create_leaderboard_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        embed = self.create_leaderboard_embed()
        await interaction.response.edit_message(embed=embed, view=self)

class MatchHistoryView(discord.ui.View):
    """A view to handle paginated match history."""
    def __init__(self, player_matches: pd.DataFrame, target_user_name: str, author_id: int):
        super().__init__(timeout=300)
        self.matches = player_matches
        self.target_user_name = target_user_name
        self.author_id = author_id
        self.current_page = 0
        self.matches_per_page = 5
        self.total_pages = (len(self.matches) - 1) // self.matches_per_page + 1
        self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who started the command can change pages.", ephemeral=True)
            return False
        return True

    def update_buttons(self):
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page >= self.total_pages - 1

    def create_history_embed(self) -> discord.Embed:
        start_index = self.current_page * self.matches_per_page
        end_index = start_index + self.matches_per_page
        page_matches = self.matches.iloc[start_index:end_index]

        embed = discord.Embed(title=f"📜 Match History for {self.target_user_name}", color=discord.Color.dark_gold())

        if page_matches.empty:
            embed.description = "No matches on this page."
        else:
            for _, match in page_matches.iterrows():
                match_time = pd.to_datetime(match['timestamp']).strftime('%Y-%m-%d')
                winner = match['winner']
                team1_ids = match['team1_ids'].split(',')
                team2_ids = match['team2_ids'].split(',')
                
                result = "Abandoned"
                if winner != 'Abandoned':
                    if str(self.matches.name) in team1_ids and winner == '🔵 Blue Team': result = "Win"
                    elif str(self.matches.name) in team2_ids and winner == '🔴 Red Team': result = "Win"
                    else: result = "Loss"

                embed.add_field(name=f"📅 {match_time} - Result: {result}", value=f"ID: `{match['match_id']}`", inline=False)

        embed.set_footer(text=f"Page {self.current_page + 1} of {self.total_pages}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        embed = self.create_history_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        embed = self.create_history_embed()
        await interaction.response.edit_message(embed=embed, view=self)

class CaptainsPickView(discord.ui.View):
    def __init__(self, author_id: int, matchmaking_cog, captains: list, available_players: list, team1: list, team2: list):
        super().__init__(timeout=900)
        self.author_id = author_id
        self.cog = matchmaking_cog
        self.captains = captains # [captain1_dict, captain2_dict]
        self.available_players = available_players
        self.team1 = team1
        self.team2 = team2
        # Start with Captain 1 (index 0) for the first pick.
        self.current_picker_index = 0
        self.picks_to_make = 1
        self.pick_turn = 1 # Tracks which pick turn we are on (1-2-2-2-1)
        self.update_player_select()

    def update_player_select(self):
        """Updates the player selection dropdown."""
        # Clear all previous components to ensure a fresh state.
        self.clear_items()
        options = [discord.SelectOption(label=p['display_name'], value=str(p['discord_id'])) for p in self.available_players]
        num_picks = self.picks_to_make
        
        player_select = discord.ui.Select(
            custom_id="player_select", # Add a custom_id to retrieve the values later
            placeholder=f"Captain {self.captains[self.current_picker_index]['display_name']}, pick {num_picks} player(s)...",
            options=options,
            min_values=num_picks,
            max_values=num_picks
        )

        async def select_callback(interaction: discord.Interaction):
            # This callback's only job is to acknowledge the interaction when the user
            # changes their selection. The actual submission logic is handled by the button.
            # This prevents the "Interaction failed" message if the user clicks away.
            await interaction.response.defer()

        player_select.callback = select_callback
        self.add_item(player_select)
        
        # Add a submit button
        submit_button = discord.ui.Button(label="Submit Pick", style=discord.ButtonStyle.success, emoji="✅")
        submit_button.callback = self.on_submit_pick
        self.add_item(submit_button)
        
        cancel_button = discord.ui.Button(label="Cancel Draft", style=discord.ButtonStyle.secondary, emoji="❌", row=1)
        cancel_button.callback = self.cancel_draft
        self.add_item(cancel_button)

    async def cancel_draft(self, interaction: discord.Interaction):
        """Cancels the captain's draft."""
        await interaction.response.edit_message(content="Captain's draft has been cancelled.", embed=None, view=None)
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        picker_id = self.captains[self.current_picker_index]['discord_id']

        # For test suite: allow the original author to pick for dummy players (negative IDs)
        # This check now applies to the button press
        if (picker_id < 0 and interaction.user.id == self.author_id):
            return True

        # For real matches: only the current captain can pick
        if interaction.user.id != picker_id:
            await interaction.response.send_message(f"It's not your turn to pick! Waiting for <@{picker_id}>.", ephemeral=True)
            return False
        return True

    async def on_submit_pick(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Find the select menu and get its values
        select_menu = discord.utils.get(self.children, custom_id="player_select")
        if not select_menu or not select_menu.values:
            # This case should ideally not happen if min_values is set correctly
            await interaction.followup.send("You must select a player.", ephemeral=True)
            return

        picked_ids = [int(val) for val in select_menu.values]
        
        # Move picked players to the correct team
        current_team = self.team1 if self.current_picker_index == 0 else self.team2
        for pid in picked_ids:
            player_to_move = next(p for p in self.available_players if p['discord_id'] == pid)
            current_team.append(player_to_move)
            self.available_players.remove(player_to_move)

        # After turn 4, there is one player left. Automatically assign them and end the draft.
        if self.pick_turn == 4 and len(self.available_players) == 1:
            last_player = self.available_players.pop(0)
            # Red team (index 1) just picked, so the last player goes to Blue team (index 0).
            self.team1.append(last_player)

            await self.cog.finalize_match(interaction, self.team1, self.team2)
            self.stop()
            return

        # If the draft is not over, set up the next turn.
        self.pick_turn += 1

        # Alternate the picker
        self.current_picker_index = 1 - self.current_picker_index 
        # Set picks to 2 for turns 2, 3, 4, and 1 for the last turn (5)
        self.picks_to_make = 1 if self.pick_turn == 5 else 2
        self.update_player_select()

        embed = self.cog.create_captains_embed(self.captains, self.team1, self.team2, self.available_players)
        await interaction.edit_original_response(embed=embed, view=self)


class Matchmaking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_matches = {} # { channel_id: { match_id, team1, team2 } }
        self.pending_matches = {} # { channel_id: { team1, team2 } }
        self.silenced_mentions = False # Global toggle for using mentions

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handles errors for commands in this cog."""
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        else:
            logging.error(f"An error occurred in a matchmaking command: {error}", exc_info=True)
            await interaction.response.send_message("An unexpected error occurred. Please check the logs.", ephemeral=True)

    async def get_player_list_from_args(self, interaction: discord.Interaction, player1, player2, player3, player4, player5, player6, player7, player8, player9, player10):
        player_members = [player1, player2, player3, player4, player5, player6, player7, player8, player9, player10]
        
        if len(set(p.id for p in player_members)) != 10:
            await interaction.response.send_message("Please provide 10 unique players.", ephemeral=True)
            return None

        await interaction.response.defer()
        players_data = [get_or_create_player(p.id, p.display_name).to_dict() for p in player_members]
        return players_data

    def create_team_embed(self, team1: list, team2: list, footer_text: str = "Use the buttons below to manage the teams.", use_mentions: bool = False):
        """Creates a standard embed for displaying two teams."""
        embed = discord.Embed(title="⚔️ Proposed Teams ⚔️", color=discord.Color.gold())

        team1_avg_rating = int(sum(p['rating'] for p in team1) / 5) if team1 else 0
        team2_avg_rating = int(sum(p['rating'] for p in team2) / 5) if team2 else 0

        def format_player_list(team):
            if not team: return "No players yet."
            if use_mentions:
                return '\n'.join([f"<@{p['discord_id']}> `({int(p['rating'])})`" for p in team])
            return '\n'.join([f"{p['display_name']} `({int(p['rating'])})`" for p in team])

        team1_mentions = format_player_list(team1)
        team2_mentions = format_player_list(team2)

        embed.add_field(name=f"🔵 Blue Team (Avg. {team1_avg_rating})", value=team1_mentions, inline=True)
        embed.add_field(name=f"🔴 Red Team (Avg. {team2_avg_rating})", value=team2_mentions, inline=True)
        embed.set_footer(text=footer_text)
        return embed

    @app_commands.command(name="recommend_teams", description="Recommends balanced teams with options to edit and confirm.")
    @app_commands.describe(
        player1="Player 1", player2="Player 2", player3="Player 3", player4="Player 4", player5="Player 5",
        player6="Player 6", player7="Player 7", player8="Player 8", player9="Player 9", player10="Player 10"
    )
    async def recommend_teams(self, interaction: discord.Interaction,
                              player1: discord.Member, player2: discord.Member, player3: discord.Member,
                              player4: discord.Member, player5: discord.Member, player6: discord.Member,
                              player7: discord.Member, player8: discord.Member, player9: discord.Member,
                              player10: discord.Member):
        """Recommends balanced teams and provides options to edit and confirm."""
        if interaction.channel_id in self.active_matches:
            await interaction.response.send_message(
                "There is already an active match in this channel. Please use `/report_match` to report the result before starting a new one.",
                ephemeral=True
            )
            return
        players_data = await self.get_player_list_from_args(interaction, player1, player2, player3, player4, player5, player6, player7, player8, player9, player10)
        if players_data is None: # Error was already sent
            return

        team1, team2 = balance_teams(players_data)

        self.pending_matches[interaction.channel_id] = {"team1": team1, "team2": team2}

        # Use display names for proposed teams to avoid spam
        embed = self.create_team_embed(team1, team2, use_mentions=False)
        view = CreateTeamsView(interaction.user.id, self, team1, team2)

        await interaction.followup.send(embed=embed, view=view)

    def create_captains_embed(self, captains, team1, team2, available):
        """Creates the embed for the captain's pick screen."""
        use_mentions = not self.silenced_mentions
        embed = discord.Embed(title="👑 Captain's Pick 👑", color=discord.Color.dark_teal())
        if use_mentions:
            embed.description = f"Captains: <@{captains[0]['discord_id']}> vs <@{captains[1]['discord_id']}>"
        else:
            embed.description = f"Captains: {captains[0]['display_name']} vs {captains[1]['display_name']}"

        team1_mentions = '\n'.join([p['display_name'] for p in team1])
        team2_mentions = '\n'.join([p['display_name'] for p in team2])
        available_mentions = ', '.join([p['display_name'] for p in available])

        embed.add_field(name=f"🔵 Team {captains[0]['display_name']}", value=team1_mentions, inline=True)
        embed.add_field(name=f"🔴 Team {captains[1]['display_name']}", value=team2_mentions, inline=True)
        embed.add_field(name="Available Players", value=available_mentions, inline=False)
        return embed

    async def finalize_match(self, interaction: discord.Interaction, team1: list, team2: list):
        """Confirms a match from captain's pick and updates the message."""
        match_id = int(datetime.now().timestamp())
        self.active_matches[interaction.channel_id] = {
            "match_id": match_id,
            "team1": team1,
            "team2": team2
        }
        # Use mentions here because the match is confirmed and players should be notified.
        use_mentions = not self.silenced_mentions
        embed = self.create_team_embed(team1, team2, use_mentions=use_mentions)
        embed.title = "⚔️ Teams Drafted & Match Confirmed! ⚔️"
        embed.set_footer(text=f"Match ID: {match_id}. Use /report_match to record the winner.")
        await interaction.edit_original_response(content="Draft complete!", embed=embed, view=None)

    @app_commands.command(name="captains_pick", description="Start a match with a captain's draft.")
    @app_commands.describe(
        player1="Player 1", player2="Player 2", player3="Player 3", player4="Player 4", player5="Player 5",
        player6="Player 6", player7="Player 7", player8="Player 8", player9="Player 9", player10="Player 10",
        captain1="Optional: Select the first captain.",
        captain2="Optional: Select the second captain."
    )
    async def captains_pick(self, interaction: discord.Interaction,
                            player1: discord.Member, player2: discord.Member, player3: discord.Member,
                            player4: discord.Member, player5: discord.Member, player6: discord.Member,
                            player7: discord.Member, player8: discord.Member, player9: discord.Member,
                            player10: discord.Member,
                            captain1: discord.Member = None,
                            captain2: discord.Member = None):
        """Starts an interactive draft to create two teams."""
        if interaction.channel_id in self.active_matches:
            await interaction.response.send_message(
                "There is already an active match in this channel. Please use `/report_match` to report the result before starting a new one.",
                ephemeral=True
            )
            return
        players_data = await self.get_player_list_from_args(interaction, player1, player2, player3, player4, player5, player6, player7, player8, player9, player10)
        if players_data is None:
            return

        captains = []
        # If captains are manually selected
        if captain1 and captain2:
            player_ids = {p['discord_id'] for p in players_data}
            if captain1.id not in player_ids or captain2.id not in player_ids:
                await interaction.followup.send("Selected captains must be part of the 10 players provided for the match.", ephemeral=True)
                return
            if captain1.id == captain2.id:
                await interaction.followup.send("Please select two different captains.", ephemeral=True)
                return
            
            c1_data = next((p for p in players_data if p['discord_id'] == captain1.id), None)
            c2_data = next((p for p in players_data if p['discord_id'] == captain2.id), None)
            captains = [c1_data, c2_data]
        # If no captains are selected, choose randomly
        else:
            import random
            captains = random.sample(players_data, 2)

        captain1_data = captains[0]
        captain2_data = captains[1]

        # The rest of the players are available to be picked
        available_players = [p for p in players_data if p not in captains]

        team1 = [captain1_data]
        team2 = [captain2_data]

        # Create and send the initial state
        embed = self.create_captains_embed(captains, team1, team2, available_players)
        view = CaptainsPickView(interaction.user.id, self, captains, available_players, team1, team2)
        
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="report_match", description="Reports the result of the last recommended match in this channel.")
    @app_commands.describe(winner="Which team won the game?")
    @app_commands.choices(winner=[
        app_commands.Choice(name="🔵 Blue Team", value="blue"),
        app_commands.Choice(name="🔴 Red Team", value="red"),
        app_commands.Choice(name="🏳️ Abandoned", value="abandoned"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def report_match(self, interaction: discord.Interaction, winner: app_commands.Choice[str]):
        """Reports the winner, updates ratings, and saves the match."""
        if interaction.channel_id not in self.active_matches:
            await interaction.response.send_message("No active match found in this channel. Use `/recommend_teams` first.", ephemeral=True)
            return

        await interaction.response.defer()

        match_info = self.active_matches.pop(interaction.channel_id)

        # Handle abandoned matches
        if winner.value == 'abandoned':
            # --- Save match record ---
            if not os.path.exists(MATCHES_CSV_PATH):
                matches_df = pd.DataFrame(columns=['match_id', 'winner', 'team1_ids', 'team2_ids', 'timestamp'])
            else:
                matches_df = pd.read_csv(MATCHES_CSV_PATH)

            new_match = pd.DataFrame([{
                'match_id': match_info['match_id'],
                'winner': 'Abandoned',
                'team1_ids': ','.join(str(p['discord_id']) for p in match_info['team1']),
                'team2_ids': ','.join(str(p['discord_id']) for p in match_info['team2']),
                'timestamp': datetime.now().isoformat()
            }])
            matches_df = pd.concat([matches_df, new_match], ignore_index=True)
            matches_df.to_csv(MATCHES_CSV_PATH, index=False)

            logging.info(f"Match {match_info['match_id']} reported as Abandoned.")

            embed = discord.Embed(title="🏳️ Match Abandoned 🏳️", description="The active match has been cleared. No ratings were changed.", color=discord.Color.light_grey())
            embed.set_footer(text=f"Match ID: {match_info['match_id']}")
            await interaction.followup.send(embed=embed)
            return

        team1, team2 = match_info['team1'], match_info['team2']
        score = 1 if winner.value == 'blue' else 0

        # --- Calculate new ratings ---
        ratings_team_1 = [(p['rating'], p['deviation']) for p in team1]
        ratings_team_2 = [(p['rating'], p['deviation']) for p in team2]

        new_ratings_team_1, new_ratings_team_2, delta_team1, delta_team2 = new_team_ratings(
            ratings_team_1, ratings_team_2, score
        )

        # --- Update player data ---
        players_df = get_player_data()
        for i, player in enumerate(team1):
            new_rating, new_dev = new_ratings_team_1[i]
            players_df.loc[players_df['discord_id'] == player['discord_id'], ['rating', 'deviation']] = new_rating, new_dev
        for i, player in enumerate(team2):
            new_rating, new_dev = new_ratings_team_2[i]
            players_df.loc[players_df['discord_id'] == player['discord_id'], ['rating', 'deviation']] = new_rating, new_dev
        save_player_data(players_df)

        # --- Save match record ---
        if not os.path.exists(MATCHES_CSV_PATH):
            matches_df = pd.DataFrame(columns=['match_id', 'winner', 'team1_ids', 'team2_ids', 'timestamp'])
        else:
            matches_df = pd.read_csv(MATCHES_CSV_PATH)

        new_match = pd.DataFrame([{
            'match_id': match_info['match_id'],
            'winner': winner.name,
            'team1_ids': ','.join(str(p['discord_id']) for p in team1),
            'team2_ids': ','.join(str(p['discord_id']) for p in team2),
            'timestamp': datetime.now().isoformat()
        }])
        matches_df = pd.concat([matches_df, new_match], ignore_index=True)
        matches_df.to_csv(MATCHES_CSV_PATH, index=False)

        logging.info(f"Match {match_info['match_id']} reported. Winner: {winner.name}")

        # --- Create result embed ---
        embed_color = discord.Color.blue() if winner.value == 'blue' else discord.Color.red()
        embed = discord.Embed(title=f"🏆 Match Result: {winner.name} Wins! 🏆", color=embed_color)

        updated_players_df = get_player_data()

        def get_updated_player_field(team, deltas):
            lines = []
            use_mentions = not self.silenced_mentions
            for i, p_orig in enumerate(team):
                p_updated = updated_players_df[updated_players_df['discord_id'] == p_orig['discord_id']].iloc[0]
                delta_str = f"{deltas[i]:+.0f}"
                player_ref = f"<@{p_updated['discord_id']}>" if use_mentions else p_updated['display_name']

                lines.append(f"{player_ref} `{int(p_updated['rating'])}` (**{delta_str})**")
            return '\n'.join(lines)

        blue_field = get_updated_player_field(team1, delta_team1)
        red_field = get_updated_player_field(team2, delta_team2)

        embed.add_field(name="🔵 Blue Team", value=blue_field, inline=True)
        embed.add_field(name="🔴 Red Team", value=red_field, inline=True)
        embed.set_footer(text=f"Match ID: {match_info['match_id']}")

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="Shows the top 10 players by rating.")
    async def leaderboard(self, interaction: discord.Interaction):
        """Displays the rating leaderboard."""
        await interaction.response.defer()
        players_df = get_player_data()

        if players_df.empty:
            await interaction.followup.send("No players found. Play a match to get on the board!")
            return

        # Sort players and reset the index to ensure ranks are correct (0, 1, 2, ...)
        sorted_players = players_df.sort_values(by='rating', ascending=False).reset_index(drop=True)

        # Create and send the paginated view
        view = LeaderboardView(sorted_players, interaction.user.id)
        embed = view.create_leaderboard_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="rating", description="Check a player's rating.")
    @app_commands.describe(player="The player to check (defaults to you).")
    async def rating(self, interaction: discord.Interaction, player: discord.Member = None):
        """Shows the rating for a specific player or the command user."""
        target_user = player or interaction.user
        await interaction.response.defer(ephemeral=True)

        player_data = get_or_create_player(target_user.id, target_user.display_name)

        embed = discord.Embed(
            title=f"📊 Rating for {player_data['display_name']}",
            color=discord.Color.green()
        )
        embed.add_field(name="Rating", value=f"`{int(player_data['rating'])}`", inline=True)
        embed.add_field(name="Deviation", value=f"`±{int(player_data['deviation'])}`", inline=True)
        
        # Find number of matches played
        if os.path.exists(MATCHES_CSV_PATH):
            matches_df = pd.read_csv(MATCHES_CSV_PATH)
            matches_played = matches_df[
                matches_df['team1_ids'].astype(str).str.contains(str(target_user.id)) |
                matches_df['team2_ids'].astype(str).str.contains(str(target_user.id))
            ].shape[0]
            embed.add_field(name="Matches Played", value=f"`{matches_played}`", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="match_history", description="View a player's recent match history.")
    @app_commands.describe(player="The player to check (defaults to you).")
    async def match_history(self, interaction: discord.Interaction, player: discord.Member = None):
        """Shows a paginated match history for a player."""
        target_user = player or interaction.user
        await interaction.response.defer(ephemeral=True)

        if not os.path.exists(MATCHES_CSV_PATH):
            await interaction.followup.send("No match history found.", ephemeral=True)
            return

        matches_df = pd.read_csv(MATCHES_CSV_PATH)
        player_matches = matches_df[
            matches_df['team1_ids'].astype(str).str.contains(str(target_user.id)) |
            matches_df['team2_ids'].astype(str).str.contains(str(target_user.id))
        ].sort_values(by='timestamp', ascending=False).reset_index(drop=True)

        if player_matches.empty:
            await interaction.followup.send(f"{target_user.display_name} has not played any recorded matches.", ephemeral=True)
            return
        
        player_matches.name = target_user.id # Attach id for win/loss calculation
        view = MatchHistoryView(player_matches, target_user.display_name, interaction.user.id)
        embed = view.create_history_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="cancel_match", description="[Admin] Cancels the current active match in the channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def cancel_match(self, interaction: discord.Interaction):
        """Cancels and removes an active match without recording it."""
        if interaction.channel_id not in self.active_matches:
            await interaction.response.send_message("There is no active match in this channel to cancel.", ephemeral=True)
            return

        match_info = self.active_matches.pop(interaction.channel_id)
        logging.info(f"Match {match_info['match_id']} cancelled by {interaction.user.display_name}.")
        await interaction.response.send_message("The active match has been cancelled.", ephemeral=True)

    @app_commands.command(name="edit_rating", description="[Admin] Manually sets a player's rating.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(player="The player whose rating you want to change.", rating="The new rating value.")
    async def edit_rating(self, interaction: discord.Interaction, player: discord.Member, rating: int):
        """Manually edits a player's rating."""
        await interaction.response.defer(ephemeral=True)
        players_df = get_player_data()
        
        player_exists = players_df['discord_id'] == player.id
        if not player_exists.any():
            get_or_create_player(player.id, player.display_name)
            players_df = get_player_data() # Re-fetch after creation

        players_df.loc[players_df['discord_id'] == player.id, 'rating'] = rating
        save_player_data(players_df)
        logging.info(f"Admin {interaction.user.display_name} set {player.display_name}'s rating to {rating}.")
        await interaction.followup.send(f"Successfully updated {player.display_name}'s rating to `{rating}`.", ephemeral=True)

    @app_commands.command(name="toggle_mentions", description="[Admin] Toggles whether the bot uses @mentions in match embeds.")
    @app_commands.checks.has_permissions(administrator=True)
    async def toggle_mentions(self, interaction: discord.Interaction):
        """Toggles the silenced_mentions setting."""
        self.silenced_mentions = not self.silenced_mentions
        new_state = "SILENCED (no pings)" if self.silenced_mentions else "ENABLED (pings active)"
        await interaction.response.send_message(f"Bot mentions are now **{new_state}**.", ephemeral=True)

    # @app_commands.command(name="test_suite", description="Runs test scenarios for matchmaking commands.")
    # @app_commands.checks.has_permissions(administrator=True)
    # @app_commands.describe(scenario="Which test scenario to run?")
    # @app_commands.choices(scenario=[
    #     app_commands.Choice(name="Recommend Teams", value="recommend"),
    #     app_commands.Choice(name="Captains Pick", value="captains"),
    # ])
    # async def test_suite(self, interaction: discord.Interaction, scenario: app_commands.Choice[str]):
    #     """Runs a test scenario using pre-configured test data."""
    #     await interaction.response.defer()

    #     # Pre-configured test players. Using negative IDs to avoid real user collisions.
    #     test_players_info = [
    #         {'id': -1, 'name': 'TestPlayer1'}, {'id': -2, 'name': 'TestPlayer2'},
    #         {'id': -3, 'name': 'TestPlayer3'}, {'id': -4, 'name': 'TestPlayer4'},
    #         {'id': -5, 'name': 'TestPlayer5'}, {'id': -6, 'name': 'TestPlayer6'},
    #         {'id': -7, 'name': 'TestPlayer7'}, {'id': -8, 'name': 'TestPlayer8'},
    #         {'id': -9, 'name': 'TestPlayer9'}, {'id': -10, 'name': 'TestPlayer10'},
    #     ]

    #     players_data = [get_or_create_player(p['id'], p['name']).to_dict() for p in test_players_info]

    #     if scenario.value == "recommend":
    #         team1, team2 = balance_teams(players_data)
    #         self.pending_matches[interaction.channel_id] = {"team1": team1, "team2": team2}
    #         embed = self.create_team_embed(team1, team2)
    #         view = CreateTeamsView(interaction.user.id, self, team1, team2)
    #         await interaction.followup.send(f"Running `{scenario.name}` test.", embed=embed, view=view)

    #     elif scenario.value == "captains":
    #         import random
    #         captains = random.sample(players_data, 2)
    #         captain1_data, captain2_data = captains[0], captains[1]
    #         available_players = [p for p in players_data if p not in captains]
    #         team1 = [captain1_data]
    #         team2 = [captain2_data]

    #         embed = self.create_captains_embed(captains, team1, team2, available_players)
    #         view = CaptainsPickView(interaction.user.id, self, captains, available_players, team1, team2)
    #         await interaction.followup.send(f"Running `{scenario.name}` test.", embed=embed, view=view)
    #     else:
    #         await interaction.followup.send("Invalid test scenario selected.", ephemeral=True)


async def setup(bot: commands.Bot):
    # Using commands.Bot to add cogs requires this setup function.
    # We'll call this from the main file.
    await bot.add_cog(Matchmaking(bot))