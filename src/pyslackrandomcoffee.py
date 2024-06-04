#!/usr/bin/env python

import os
import time
import random
import logging
import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv, find_dotenv

# Setup - this function requires the SLACK_API_TOKEN environmental variable to run.
_ = load_dotenv(find_dotenv())
slack_token = os.getenv('SLACK_API_TOKEN')
channel_name = os.getenv('CHANNEL_NAME')
channel_name_testing = os.getenv('CHANNEL_NAME_TESTING')
private_channel_name = os.getenv('PRIVATE_CHANNEL_NAME_FOR_MEMORY')
pairs_are_public = os.getenv("PAIRS_ARE_PUBLIC", 'False').lower() in ('true', 't', 'yes', 'y', '1')
testing = os.getenv("TESTING_MODE", 'False').lower() in ('true', 't', 'yes', 'y', '1')
chan_names_are_ids = os.getenv("CHAN_NAMES_ARE_IDS", 'False').lower() in ('true', 't', 'yes', 'y', '1')

LOOKBACK_DAYS   = int(os.getenv('LOOKBACK_DAYS'))
MAGICAL_TEXT    = os.getenv('MAGICAL_TEXT')

client = WebClient(token=slack_token)

def get_bot_user_id():
    try:
        test = client.auth_test()
        return test["user_id"]
    except SlackApiError as e:
        logging.error(f"Error getting bot's user id: {e}")
        return None

def get_channels_id(channels):
    '''Convert a human readable channel name into a slack channel ID that can be used in the API.

    Args:
        channels: Array of human readable channel names, such as ['randomcoffees','randomcoffeesbotmemory']

    Returns:
        channels_id: A dict with channel names as key, and Slack ID for the channel, such as CE2G4C9L2, as values
    '''

    if chan_names_are_ids:
        return { chan : chan for chan in channels }

    chan_name_to_id = { chan : None for chan in channels }

    try:
        # Get the channel ID of the channel
        # The results paginated, so loop until we get the them all. https://api.slack.com/methods/conversations.history
        conversation_history = []
        has_more = True
        next_cursor = None
        channel_id = None
        while has_more:
            response = client.conversations_list(limit=200, cursor=next_cursor, types='public_channel,private_channel')
            channel_list = response["channels"]
            logging.info(f"Retrieved {len(channel_list)} chans")
            for c in channel_list:
                if c.get('name') in chan_name_to_id.keys():
                    chan_name_to_id[c.get('name')] = c['id']
            if not None in chan_name_to_id.values():
                break
            else:
                has_more = response['response_metadata'] is not None and response['response_metadata']['next_cursor']
                if has_more:
                    next_cursor = response['response_metadata']['next_cursor']
                    logging.info('Waiting before next page of channels list.')
                    logging.info(f"Currently retrieved: {chan_name_to_id}")
                    time.sleep(10) # Prevent API rate-limiting


        return chan_name_to_id

    except SlackApiError as e:
        logging.error(f"Error getting channels ID: {channels}: {e}")
        return None


def get_previous_pairs(channel_id, testing, bot_user_id, lookback_days=LOOKBACK_DAYS, members_count=1000):
    '''
    Trawl through the messages in the channel and find those that contain magical text and extract the pairs from these
    messages.

    Args:
        channel (str): ID of the channel where previous pairs were posted, i.e. C01234567
        testing (bool): A flag to use either @user1 or UABCDEFG1 syntax
        lookback_days (int): How man days back should the function look for previous messages

    Returns:
        previous_pairs (list of of list of tuples):
            [
                [('UABCDEFG1', 'UABCDEFG2'), ('UABCDEFG5', 'UABCDEFG7')],
                [('UABCDEFG3', 'UABCDEFG4'), ('UABCDEFG6', 'UABCDEFG8')]
            ]

    Note:
        The formatting of the names depends if in the job is in testing mode or not. The text @user1 will not generate
        notify the user1, but it will look like the correct link (but not blue). <@UABCDEFG1> on the other hand will
        notify the link and be a blue link that looks like @user1 in slack.
    '''

    try:
        # Setup params for client.conversations_history(). slack accepts time in seconds since epoch
        params = {
            'channel': channel_id, 
            'limit': 200,  # Pagination - 200 messages per API call
            'oldest': (datetime.datetime.today() - datetime.timedelta(days=lookback_days)).timestamp(),
            'newest': datetime.datetime.now().timestamp()
        }

        # The results paginated, so loop until we get the them all. https://api.slack.com/methods/conversations.history
        conversation_history = []
        has_more = True
        next_cursor = None
        while has_more:
            response = client.conversations_history(**params, cursor=next_cursor)
            conversation_history += response["messages"]
            has_more = response['has_more']
            if has_more:
                next_cursor = response['response_metadata']['next_cursor']
                logging.info('Waiting before next page of convo history')
                time.sleep(1) # Prevent API rate-limiting

    except SlackApiError as e:
        logging.error(f"Error getting conversation history for {channel}: {e}")

    logging.info(f"Convo history has {len(conversation_history)} messages")
    # Focus on the bot's own messages
    if bot_user_id:
        conversation_history = [ message for message in conversation_history if message["user"] == bot_user_id ]
    # Don't keep more than members count - 2 messages
    conversation_history = conversation_history[:min(len(conversation_history), members_count - 2)]

    logging.info(f"Keeping {len(conversation_history)} from the bot")

    # We are only interested in text that contain the MAGICAL_TEXT text and '<@U' (in prod) or '@' in testing.
    strip_len_start=0
    strip_len_end=0
    if testing:
        texts = [t['text'] for t in conversation_history if MAGICAL_TEXT in t['text'] and '@' in t['text']]
        strip_len_start=1
    else:
        texts = [t['text'] for t in conversation_history if MAGICAL_TEXT in t['text'] and '<@U' in t['text']]
        strip_len_start=2
        strip_len_end=1

    if len(texts):
        # Each message text is a broken into a list by the newline character and the first and last line are disregarded
        # as they are not pairs. Then each pair is cleaned and the username is extracted the result is a list of list of
        # tupples. Example:
        # [
        #     [('UABCDEFG1', 'UABCDEFG2'), ('UABCDEFG5', 'UABCDEFG7')],
        #     [('UABCDEFG3', 'UABCDEFG4'), ('UABCDEFG6', 'UABCDEFG8')]
        # ]
        previous_pairs = [
            [
                (
                    e.split('. ')[1].split('and')[0].strip()[strip_len_start:-strip_len_end],
                    e.split('. ')[1].split('and')[1].strip()[strip_len_start:-strip_len_end]
                ) for e in t.split('\n')[1:-1]
            ] for t in texts
        ]
    else:
        previous_pairs = None

    return previous_pairs


def post_to_slack_channel_message(message, channel_id):
    '''Send a message to a given slack channel.

    Args:
        message (str): Message to send
        channel_id (str): ID of the receiving channel (ex. C01234567) or the unique user id for sending private
            messages

    Returns:
        bool: True of message was a send with success. False otherwise.
    '''

    try:
        if isinstance(message, list):
            # The user would like to send a block
            response = client.chat_postMessage(channel=channel_id, blocks=message)
        else:
            response = client.chat_postMessage(channel=channel_id, text=message)
    except SlackApiError as e:
        # From v2.x of the slack library failed responses are raised as errors. Here we catch the exception and
        # downgrade the alert
        logging.error(f"Error posting in {channel}: {e}")
        return False
    else:
        # Capture soft problems
        if not response['ok']:
            print(response)
            return False
        else:
            return True


def get_members_list(channel_id, testing):
    '''Get the list of members of a channel.

    Args:
        channel (str): ID of the channel i.e. "C01234567".
        testing (bool): If True inactive usernames are written that does not notify the users, but if False active
            username links are used and the users are pinged when the message is posted

    Returns:
        members: Returns a list of users.
            If testing is True:  ['@user1', '@user2', '@user3', '@user4']
            If testing is False: ['UABCDEFG1', 'UABCDEFG2', 'UABCDEFG3', 'UABCDEFG4']

    Note:
        The formatting of the names depends if in the job is in testing mode or not. The text @user1 will not generate
        notify the user1, but it will look like the correct link (but not blue). UABCDEFG1 on the other hand will
        notify the link and be a blue link that looks like @user1 in slack.
    '''

    try:
        # Handle pagination to break through 1000 users hard limit
        member_ids=[]
        has_more = True
        next_cursor = None
        while has_more:
            response = client.conversations_members(limit=200, channel=channel_id, cursor=next_cursor)
            member_ids.extend(response['members'])
            has_more = response['response_metadata'] is not None and response['response_metadata']['next_cursor']
            if has_more:
                next_cursor = response['response_metadata']['next_cursor']
                logging.info('Waiting before next page of channels members list.')
                logging.info(f"Currently retrieved: {len(member_ids)}")
                time.sleep(5) # Prevent API rate-limiting

        members = []
        for member_id in member_ids:
            user = client.users_info(user=member_id)['user']
            if not user['is_bot']:
                if testing:
                    members.append(f'@{user["name"]}')
                else:
                    members.append(f'{user["id"]}')

        logging.info(f"Found {len(members)} members")

        return members

    except SlackApiError as e:
        logging.error(f"Error getting list of members in {channel_id}: {e}")
        return None


def generate_pairs(members, previous_pairs=None):
    '''
    Shuffles the members list around and pairs them. If ther is uneven number of members one member will be matched
    twice. If there are no members (empty list) it will return an empty list. If the previous_pairs are present they
    will be used to avoid matching members up with previous matches. This is not also possible if there are few members.

    Args:
        members (list of strings): i.e. ['UABCDEFG1', 'UABCDEFG2', 'UABCDEFG3', 'UABCDEFG4']
        previous_pairs (list of list of tuples):
            [
                [('UABCDEFG1', 'UABCDEFG2'), ('UABCDEFG5', 'UABCDEFG7')],
                [('UABCDEFG3', 'UABCDEFG4'), ('UABCDEFG6', 'UABCDEFG8')]
            ]

    Returns:
        pairs (list of tupples): i.e. [('UABCDEFG1', 'UABCDEFG2'), ('UABCDEFG3', 'UABCDEFG4')]

    Note:
        The formatting of the names depends if in the job is in testing mode or not. The text @user1 will not generate
        notify the user1, but it will look like the correct link (but not blue). <@UABCDEFG1> on the other hand will
        notify the link and be a blue link that looks like @user1 in slack.
    '''

    # Shuffle the channel members around
    random.shuffle(members)

    # For each memeber find previous matches. TODO: This is nasty, but premature optimization is the root of all evil.
    # The stored format is a list of lists of tuples with previous matches:
    #     [[...], [('@tk', '@abl'), ('@sh', '@lbr'), ('@tk', '@tj')], [...], ...]
    # This code turns that into a dict structure with unique matches
    #     members_previous_matches = {@cjb: [@tj,...]}
    members_previous_matches = {}
    if members and previous_pairs:
        for member in members:
            matches = []
            for pair_set in previous_pairs:
                for p1, p2 in pair_set:
                    if p1 == member or p2 == member:
                        if p1 == member:
                            matches.append(p2)
                        elif p2 == member:
                            matches.append(p1)
            members_previous_matches[member] = list(set(matches))

    def pair_excluding_historic_matches(member1, members, members_previous_matches):
        '''Walkthrough the members list and try to find matches that has not been done before.

        Args:
            member1 (str): 'UABCDEFG1' or '@user1'
            members (list): The list of members.
            members_previous_matches (dict):
                {
                    'UABCDEFG8': ['UABCDEFG1', 'UABCDEFG2', 'UABCDEFG3'],
                    'UABCDEFG7': ['UABCDEFG1', 'UABCDEFG4'],
                }

        Returns
            pair (tuple): The input member1 and the matched member2
            memebers (list): The members list, but with member2 removed
        '''
        if members_previous_matches:
            member2_candidates = [member for member in members if member not in members_previous_matches[member1]]

            try:
                member2 = random.sample(member2_candidates, 1)[0]
            except ValueError:
                # There is no untaken matches left, so just pick a random from members
                member2 = random.sample(members, 1)[0]
        else:
            member2 = random.sample(members, 1)[0]

        members.remove(member2)
        pair = (member1, member2)

        return pair, members

    # Ensure if there is uneven number of members one member will be matched twice. If there are no members return a
    # empty list
    pairs = []
    if members:
        first_member = members[-1]
        while len(members):
            if len(members) >= 2:
                member1 = members.pop()
                pair, members = pair_excluding_historic_matches(member1, members, members_previous_matches)
            else:
                pair, members = pair_excluding_historic_matches(first_member, members, members_previous_matches)

            pairs.append(pair)

    logging.info(f"Generated {len(pairs)} pairs")

    return pairs


def format_message_from_list_of_pairs(pairs):
    '''
    Takes the list of pairs and formats the output in a slack message that can then be posted to the slack channel.

    Args:
        pairs (list of tupples): i.e. [('UABCDEFG1', 'UABCDEFG2'), ('UABCDEFG3', 'UABCDEFG4')]

    Returns:
        message (multi-line str): The message
    '''

    if len(pairs):
        m1 = MAGICAL_TEXT + ':\n'
        pair_strings = ''.join([f' {i+1}. <@{p1}> et <@{p2}>\n' for i, (p1, p2) in enumerate(pairs)])
        #m2 = f'An uneven number of members results in one person getting two coffee matches. Matches from the last {LOOKBACK_DAYS} days considered to avoid matching the same members several times in the time period.'
        m2 = f'Une personne se retrouve avec deux paires à cause d\'un nombre impair de membres. Les paires des {LOOKBACK_DAYS} derniers jours sont prises en compte pour ne pas appairer les mêmes membres plusieurs fois durant cette période.'
        message = m1 + pair_strings + m2
        return message
    else:
        return None

def mpim_all_pairs(pairs, channel_id):
    '''
    Takes the list of pairs and sends a group DM to each pair.

    Args:
        pairs (list of tupples): i.e. [('UABCDEFG1', 'UABCDEFG2'), ('UABCDEFG3', 'UABCDEFG4')]
        channel_id (str): ID of the channel were pairs will be posted for later reference, i.e. C01234567
    '''
    for pair in pairs:
        try:
            mpim=client.conversations_open(users=pair)
            #post_to_slack_channel_message(f"Hello <@{pair[0]}> and <@{pair[1]}>\nYou've been randomly selected for <#{channel_id}>!\nTake some time to meet soon.", channel_id=mpim["channel"]["id"])
            post_to_slack_channel_message(f"Bonjour <@{pair[0]}> et <@{pair[1]}>\nVous avez été sélectionnés aléatoirement pour une <#{channel_id}>!\nPrenez un peu de temps pour vous rencontrer prochainement. Ce sera l'occasion de sortir de votre quotidien et d'échanger de manière informelle et confidentielle avec d'autres personnes en formation !", channel_id=mpim["channel"]["id"])
            logging.info('Waiting before sending next mpim')
            time.sleep(1) # Prevent API rate-limiting
        except SlackApiError as e:
            logging.error(f"Error posting mpim message: {e}")

def pyslackrandomcoffee(work_ids=None, testing=False):
    '''Pairs the members of a slack channel up randomly and post it back to the channel in a message.

    Args:
        work_ids (list): Unused STAU required argument
        testing (bool): Flag if the CHANNEL_TESTING should be used.

    Note:
        This script does utilize work_ids, but STAU requires it, so it is present, but unused.
    '''

    if testing is False:
        channel = channel_name
    else:
        channel = channel_name_testing

    channel_names = [ channel ]
    
    logging.info(f"Using channel {channel}")

    if pairs_are_public:
        memory_channel = channel
    else:
        memory_channel = private_channel_name
        channel_names.append(private_channel_name)

    channel_names_to_id = get_channels_id(channel_names)

    logging.info(f"Channels ID retrieved: {channel_names_to_id}")

    channel_id  = channel_names_to_id[channel]
    memory_channel_id  = channel_names_to_id[memory_channel]
    bot_user_id    = get_bot_user_id()
    members        = get_members_list(channel_id, testing)
    previous_pairs = get_previous_pairs(memory_channel_id, testing, bot_user_id, members_count=len(members))
    pairs          = generate_pairs(members, previous_pairs)
    message        = format_message_from_list_of_pairs(pairs)
    
    mpim_all_pairs(pairs,channel_id)
    if message:
        post_to_slack_channel_message(message, memory_channel_id)
        if not pairs_are_public:
            #post_to_slack_channel_message(f"I just launched a new round of {len(pairs)} pairs! Check your DMs.", channel)
            post_to_slack_channel_message(f"Je viens de lancer une nouvelle tournée de {len(pairs)} paires! Vérifiez vos messages privés.", channel)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    pyslackrandomcoffee(testing)
