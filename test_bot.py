import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

# ── Stub out env vars and Discord/Gemini imports before importing main ──
import os
os.environ.setdefault('BOT_SECRET_TOKEN', 'fake-token')
os.environ.setdefault('GEMINI_API_KEY', 'fake-key')
os.environ.setdefault('TEST_GUILD_ID', '')

# Patch google.genai so importing main.py doesn't make real API calls
import sys
from unittest.mock import MagicMock
sys.modules.setdefault('google', MagicMock())
sys.modules.setdefault('google.genai', MagicMock())
sys.modules.setdefault('google.genai.types', MagicMock())

from main import build_gemini_conversation


def make_message(content, author_id=1, display_name='User', is_bot=False):
    """Helper to create a mock Discord message."""
    msg = MagicMock()
    msg.content = content
    msg.author.id = author_id
    msg.author.display_name = display_name
    msg.author.bot = is_bot
    return msg


def run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────
# build_gemini_conversation tests
# ─────────────────────────────────────────────

class TestBuildGeminiConversation:

    def test_empty_history_returns_empty_list(self):
        result = run(build_gemini_conversation([]))
        assert result == []

    def test_single_user_message(self):
        msgs = [make_message('hello', author_id=42, display_name='Alice')]
        result = run(build_gemini_conversation(msgs))
        assert len(result) == 1
        assert result[0]['role'] == 'user'
        assert 'Alice (<@42>): hello' in result[0]['parts'][0]['text']

    def test_bot_message_has_model_role(self):
        msgs = [make_message('I am the bot', is_bot=True)]
        result = run(build_gemini_conversation(msgs))
        assert result[0]['role'] == 'model'

    def test_bot_message_not_prefixed_with_name(self):
        msgs = [make_message('bot reply', display_name='G3 Bot', is_bot=True)]
        result = run(build_gemini_conversation(msgs))
        # Bot messages should NOT include the "NAME (<@ID>):" prefix
        assert 'G3 Bot' not in result[0]['parts'][0]['text']
        assert result[0]['parts'][0]['text'] == 'bot reply'

    def test_empty_messages_are_skipped(self):
        msgs = [
            make_message('', display_name='Alice'),
            make_message('   ', display_name='Bob'),
            make_message('actual message', display_name='Carol'),
        ]
        result = run(build_gemini_conversation(msgs))
        assert len(result) == 1
        assert 'Carol' in result[0]['parts'][0]['text']

    def test_consecutive_user_messages_are_merged(self):
        msgs = [
            make_message('first', author_id=1, display_name='Alice'),
            make_message('second', author_id=2, display_name='Bob'),
        ]
        result = run(build_gemini_conversation(msgs))
        # Both are user role — should be merged into one entry
        assert len(result) == 1
        assert result[0]['role'] == 'user'
        text = result[0]['parts'][0]['text']
        assert 'first' in text
        assert 'second' in text

    def test_consecutive_bot_messages_are_merged(self):
        msgs = [
            make_message('part one', is_bot=True),
            make_message('part two', is_bot=True),
        ]
        result = run(build_gemini_conversation(msgs))
        assert len(result) == 1
        assert result[0]['role'] == 'model'
        text = result[0]['parts'][0]['text']
        assert 'part one' in text
        assert 'part two' in text

    def test_alternating_roles_not_merged(self):
        msgs = [
            make_message('user says hi', display_name='Alice'),
            make_message('bot replies', is_bot=True),
            make_message('user follows up', display_name='Alice'),
        ]
        result = run(build_gemini_conversation(msgs))
        assert len(result) == 3
        assert result[0]['role'] == 'user'
        assert result[1]['role'] == 'model'
        assert result[2]['role'] == 'user'

    def test_user_mention_format_in_content(self):
        msgs = [make_message('hey', author_id=99, display_name='Dave')]
        result = run(build_gemini_conversation(msgs))
        assert '<@99>' in result[0]['parts'][0]['text']
        assert 'Dave' in result[0]['parts'][0]['text']

    def test_whitespace_only_messages_skipped(self):
        msgs = [
            make_message('\n\t  \n', display_name='Alice'),
            make_message('real content', display_name='Bob'),
        ]
        result = run(build_gemini_conversation(msgs))
        assert len(result) == 1
        assert 'real content' in result[0]['parts'][0]['text']
