# api-segerahabis
api for online shop segerahabis


## DB diagram
![db diagram](https://github.com/tssovi/grokking-the-object-oriented-design-interview/blob/master/media-files/online-shopping-class-diagram.png?raw=true)
the base db logic that i've been used on this project, with little bit improvement and change while working on this project... thanks alot for the example!

## Tech Stack
- SQL Server v9
- FastAPI
- Docker
- Python 

## Howto
This repo just providing the API logic, not the system entirely, so you should build your table and records db first before using this API's 
if you already have the exact table and records like the API's, here's the next step : 
1. Clone the main repo
2. Set the db and the table
3. Set the creds on Dockerfile
4. Build..... using ```docker build -t api-segerahabis```
5. Run with ```docker run -d -p 80:80 --name <desired-container-name> api-segerahabis```

## Troubleshoot
already following the step, but found or encounter some error? msg me!
