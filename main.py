# main.py

from flask import Flask, send_file
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
import chromedriver_binary 
from webdriver_manager.chrome import ChromeDriverManager
import datetime
import os
import ast
import pandas as pd
from sodapy import Socrata
import time
import requests
from bs4 import BeautifulSoup
import smtplib
import dash
import dash_bootstrap_components as dbc
from dash import html
import gunicorn
import signal
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

app = Flask(__name__)

@app.route("/", methods=["POST"])
def main():
    # The following options are required to make headless Chrome
    # work in a Docker container
    service = Service()
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--remote-debugging-port=8080")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("window-size=1024,768")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions");
    chrome_options.add_argument("--dns-prefetch-disable");
    chrome_options.add_argument("enable-automation")
    chrome_options.page_load_strategy = 'normal'
    print("Options added")

    # Input variables
    today = pd.to_datetime("today")
    last_week = list(range(1,8))
    api_calls = []
    results_df = pd.DataFrame()

    # Shape API calls for each day
    for i in last_week:
      day =  today - datetime.timedelta(days=i)
      day = day.strftime('%d-%b-%Y')
      api_calls.append("https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice?datasetId=DS00979&resourceId=RS00909&filter=publication_date="+"'"+str(day)+"'"+"&top=1000&type=json")

    # Query APIs
    for i in api_calls:
      url = i
      try:
          response = requests.get(url)
          response.raise_for_status()  # Raise an exception for 4XX and 5XX status codes
          data = response.json()  # Parse the JSON response
          print(data)  # Print the response data
      except requests.RequestException as e:
          print(f'Error: {e}')
      results_df = pd.concat([results_df, pd.DataFrame.from_records(data['data'])], ignore_index=True)
        
    trigger = 0
    if len(results_df)>0:
        # Correct date format
        results_df['publication_date'] = results_df['publication_date'].str.replace('T',' ').str[:-4]
        results_df['publication_date'] = pd.to_datetime(results_df['publication_date'])
        # Filter only procurement notices
        results_df = results_df[results_df['notice_type'] != 'Contract Award']
        # Filter only services
        results_df = results_df[(results_df['procurement_category'] != 'Works') & (results_df['procurement_category'] != 'Goods')]
        # Add treatment column
        results_df['scan'] = 'Not treated'
        print
        print("Main table structured: "+str(len(results_df.index))+"rows")

        # Key words
        browser = webdriver.Chrome(service=service, options=chrome_options)
        key_words = ['earth observation', 'Earth Observation', ' EO ', 'GIS ', ' GIS', 'geospatial', 'Geospatial', 'geographic information', 'Geographic information', 'imagery', 'Imagery', 'geotechnical', 'Geotechnical', 'remote sensing', 'Remote sensing', 'satellite', 'Satellite', 'télédétection', 'Télédétection', 'géospatial', 'Géospatial', 'SIG ', ' SIG,', 'satélite', 'Satélite', 'teledetección', 'Teledetección', 'geoespacial', 'Geoespacial', 'observación de la tierra', 'Observación de la tierra','observação da terra', 'Observação da Terra', 'informação geográfica', 'Informação geográfica', 'geotecnico', 'Geotecnico', 'deteção remota', 'Deteção remota']
    
        # Initialize browser and screen each page for the keywords
        browser = webdriver.Chrome(service=service, options=chrome_options)
        print("Browser initialized")
        for index, row in results_df.iterrows():
            print(results_df.loc[index, 'url']['url'])
            url = results_df.loc[index, 'url']['url']
            results_df.loc[index, 'url'] = url
            # Initialize a new browser
            browser.get(url)
            html = browser.page_source
        
            soup = BeautifulSoup(html, features="html.parser")
        
            # kill all script and style elements
            for script in soup(["script", "style"]):
                script.extract()    # rip it out
        
            # get text
            text = soup.get_text()
        
            # break into lines and remove leading and trailing space on each
            lines = (line.strip() for line in text.splitlines())
            # break multi-headlines into a line each
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            # drop blank lines
            text = ' '.join(chunk for chunk in chunks if chunk)
        
            if any(word in text for word in key_words):
                results_df.loc[index, 'scan'] = 'detected'
                trigger=1
                print("query found")
            elif '403 ERROR' in text:
                results_df.loc[index, 'scan'] = 'error'     
                print("error")
            else:
                results_df.loc[index, 'scan'] = 'nothing detected'
                print('no match')
        browser.close()

        results_df = results_df[(results_df['scan']=='detected')]
        results_df = results_df[['notice_type', 'project_id', 'bid_description', 'major_sector', 'url', 'submission_date', 'deadline_date', 'procurement_method_name', 'country_name', 'regionname']]
        results_df = results_df.rename(columns={'url': 'Link', 'notice_type': 'Notice Type', 'submission_date' : 'Published Date', 'project_id' : 'Project ID', 'bid_description' : 'Description', 'procurement_method_name' : 'Procurement Method', 'deadline_date' : 'Submission Deadline', 'country_name' : 'Country', 'regionname' : 'Region', 'major_sector' : 'Major Sector'})
        results_df = results_df.reset_index(drop=True)
    
    # Notification function #
    msg = MIMEMultipart()
    msg['Subject'] = "WB Project Procurements screening"
    sender = 'alex.chunet@gmail.com'
    recipients = ast.literal_eval(os.environ['recipients'])
    emaillist = [elem.strip().split(',') for elem in recipients]

    def send_email(sbjt, msg):
        toaddrs = 'alex.chunet@gmail.com'

        # The actual mail sent
        server = smtplib.SMTP('smtp.gmail.com:587')
        server.starttls()
        server.login(os.environ['email_p'],os.environ['pass_p'])
        server.sendmail(sender, emaillist, msg)
        server.quit()

    # Format email
    html = """\
    <html>
    <head></head>
    <body>
        <p1>Keywords used:  ['earth observation', 'Earth Observation', ' EO ', 'GIS ', ' GIS', 'geospatial', 'Geospatial', 'geographic information', 'Geographic information', 'imagery', 'Imagery', 'geotechnical', 'Geotechnical', 'remote sensing', 'Remote sensing', 'satellite', 'Satellite', 'télédétection', 'Télédétection', 'géospatial', 'Géospatial', 'SIG ', ' SIG,', 'satélite', 'Satélite', 'teledetección', 'Teledetección', 'geoespacial', 'Geoespacial', 'observación de la tierra', 'Observación de la tierra','observação da terra', 'Observação da Terra', 'informação geográfica', 'Informação geográfica', 'geotecnico', 'Geotecnico', 'deteção remota', 'Deteção remota']</p1>
        {0}
    </body>
    </html>
    """.format(results_df.to_html())

    part1 = MIMEText(html, 'html')
    msg.attach(part1)

    # Send 
    if trigger == 1:
        send_email('Query found', msg.as_string())
    else:
        send_email('No query found', msg.as_string())
        
    print("SUCCESS!")
    return '', 200

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
