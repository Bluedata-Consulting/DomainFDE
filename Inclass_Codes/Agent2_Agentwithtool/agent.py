import os

import requests
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool


def get_current_weather(city:str)->dict:
    """ can be used to get/fetch current weather information for a city name
    """
    api_key = ""

    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}"
    response = requests.get(url)
    response = response.content.decode()
    response = json.loads(response)
    output = {"City Name":city,"weather":response["weather"][0]['description'],
              "temperature":response['main']['temp'],
              "unit":"kelvin"}

    return output

get_current_weather_tool=FunctionTool(get_current_weather)


Instruction="""
You are a Custmoer Service Agent, responsible for greeting customers,
resolving their queries by providing knowledge to best of your ability.
if you are not sure, or there is risk, always mention the same.
Keep it friendly conversational and polite.
Do not write longer response which makes it difficult to read, keep responses less than 30 words.
you can also provide weather information if asked by customer
"""

root_agent= LlmAgent(name="greetAgent",
model='gemini-2.5-flash',
Instruction = Instruction,
description='this is a customer service agent',
tools=[get_current_weather_tool])