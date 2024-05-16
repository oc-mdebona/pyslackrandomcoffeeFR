FROM python:3-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ARG TESTING_MODE=False
ARG PAIRS_ARE_PUBLIC=False
ARG LOOKBACK_DAYS=28
ARG MAGICAL_TEXT="Les rencontres de cette semaine sont"
ARG CHAN_NAMES_ARE_IDS=False

ENV TESTING_MODE=${TESTING_MODE}
ENV PAIRS_ARE_PUBLIC=${PAIRS_ARE_PUBLIC}
ENV LOOKBACK_DAYS=${LOOKBACK_DAYS}
ENV MAGICAL_TEXT=${MAGICAL_TEXT}
ENV CHAN_NAMES_ARE_IDS=${CHAN_NAMES_ARE_IDS}

ENV SLACK_API_TOKEN="xoxb-XXXXXXXXXXXXX-XXXXXXXXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXX"
ENV CHANNEL_NAME="random-coffee"
ENV CHANNEL_NAME_TESTING="random-coffee-tests"
ENV PRIVATE_CHANNEL_NAME_FOR_MEMORY="randomcoffebotprivatechannelformemory"

COPY ./src/pyslackrandomcoffee.py .

CMD [ "python", "/app/pyslackrandomcoffee.py" ]
