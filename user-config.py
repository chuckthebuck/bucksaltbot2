import os

usernames['commons']['commons'] = 'chuckbot'

consumer_key = os.getenv("CONSUMER_TOKEN")
consumer_secret = os.getenv("CONSUMER_SECRET")
access_token = os.getenv("ACCESS_TOKEN")
access_secret = os.getenv("ACCESS_SECRET")

if not all([consumer_key, consumer_secret, access_token, access_secret]):
    raise RuntimeError("Missing OAuth environment variables")

info = (consumer_key, consumer_secret, access_token, access_secret)

# Explicit is better than wildcard
authenticate['commons.wikimedia.org'] = info