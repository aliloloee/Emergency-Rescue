from django.shortcuts import render



def main(request) :
    response = render(request, "main.html", {})
    return response
