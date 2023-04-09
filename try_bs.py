import requests
from bs4 import BeautifulSoup

def main():


    url = 'https://neva.today/tape'
    response = requests.get(url)
    print(response.status_code)

    main_bs = BeautifulSoup(response.text, 'lxml')


    title_bs = main_bs.find('h1', {'itemprop': 'headline'})
    print(title_bs)
    #body_bs = main_bs.find('div', {'class': 'articleBody'})
    #all_paragraphs = "".join([i.text for i in body_bs.find_all('p')])
    #print(all_paragraphs)


if __name__ == '__main__':
    main()
