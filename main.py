#!/usr/bin/env python3

import os
import pika
import random
from retry import retry
import logging
import base64
import json

import aes

from SwobThirdPartyPlatforms import ImportPlatform
from SwobThirdPartyPlatforms.exceptions import PlatformDoesNotExist

logging.basicConfig(level=logging.INFO)

shared_key = os.environ["PUBLISHER_DECRYPTION_KEY"]

def publishing_payload(ch, method, properties, body: bytes) -> None:
    """
    """
    logging.info("Publishing payload: %s", body)

    try:
        body = base64.b64decode(body)

        iv = body[:16]
        body = body[16:]

        body = aes.AESCipher.decrypt(data=body, shared_key=shared_key, iv=iv)

        body = json.loads(body)

    except Exception as error:
        logging.exception(error)
        ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)

    else:
        body_content = body['data']
        body_content = ':'.join(body_content.split(':')[1:])

        platform_name = body['platform_name']

        try:
            platform = ImportPlatform(platform_name=platform_name)
            platform.execute(body=body_content, user_details=body)

        except PlatformDoesNotExist as error:
            logging.exception(error)
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

        except Exception as error:
            logging.exception(error)
            # ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

        else:
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logging.info("publishing complete...")


@retry((pika.exceptions.AMQPConnectionError, pika.exceptions.AMQPHeartbeatTimeout), 
       delay=5, jitter=(1, 3))
def consumer():
    """
    """
    user = os.environ["RMQ_USER"]
    password = os.environ["RMQ_PASSWORD"]
    host = os.environ["RMQ_HOST"]

    GMAIL_CREDENTIALS=os.environ["GMAIL_CREDENTIALS"]

    queue_name = "default-smswithoutborders-queue" \
            if not os.environ.get("RMQ_QUEUE_NAME") \
            else os.environ.get("RMQ_QUEUE_NAME")
    
    routing_key = "default-smswithoutborders-routing-key" \
            if not os.environ.get("RMQ_ROUTING_KEY") \
            else os.environ.get("RMQ_ROUTING_KEY")

    exchange_name = "default-smswithoutborders-exchange" \
            if not os.environ.get("RMQ_EXCHANGE") \
            else os.environ.get("RMQ_EXCHANGE")

    connection_name = "default-smswithoutborders-consumer" \
            if not os.environ.get("RMQ_CONNECTION_NAME") \
            else os.environ.get("RMQ_CONNECTION_NAME")

    credentials=pika.PlainCredentials(user, password)

    client_properties = {'connection_name' : connection_name}

    connection = pika.BlockingConnection(pika.ConnectionParameters(
        heartbeat=30,
        blocked_connection_timeout=300,
        host=host,
        client_properties=client_properties,
        credentials=credentials))

    channel = connection.channel()

    result = channel.queue_declare(queue=queue_name, durable=True)

    channel.exchange_declare(
            exchange=exchange_name, 
            exchange_type="topic", 
            durable=True)

    channel.queue_bind(exchange=exchange_name, 
                       queue=result.method.queue, 
                       routing_key=routing_key)

    channel.basic_consume(
            queue=result.method.queue, 
            on_message_callback=publishing_payload)

    try:
        channel.start_consuming()
    except pika.exceptions.ConnectionClosedByBroker:
        logging.warning("Clean stoping broker...")
    except Exception as error:
        logging.exception(error)

if __name__ == "__main__":
    consumer()