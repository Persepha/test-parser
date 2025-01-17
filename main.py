import json
import os
import random
import re
from typing import List
import aiohttp
import time
import asyncio
from bs4 import BeautifulSoup
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://www.truckscout24.de"


class Vehicle(BaseModel):
    id: int
    href: str
    title: str
    price: int
    mileage: int
    color: str
    power: int
    description: str
    phone: str | None = None

    class Config:
        extra = "allow"


class AdList(BaseModel):
    ads: List[Vehicle]


def get_random_offer_detail_url(data: str):
    soup = BeautifulSoup(data, "html.parser")
    offers = []

    # get all offers from the page
    offers = soup.find("section", id="offer-list").find_all("section", class_="grid-card")

    if not offers:
        return

    random_offer = random.choice(offers)

    details_url = random_offer.find("section", class_="grid-body").find("a")
    if not details_url:
        return

    return BASE_URL + details_url.get("href")


def get_offer_images(data: str, id: str):
    """return offer images data list in tuple (id, index, url)"""
    soup = BeautifulSoup(data, "html.parser")
    images = soup.find("div", id=f"listingCarousel{id}").find_all("img")

    if not images:
        return []

    return [
        (id, i, image.get("data-src") if image.has_attr("data-src") else image.get("src"))
        for i, image in enumerate(images)
    ][:3]


def get_offer_id(soup: BeautifulSoup):
    """get offer id if it exists else generate random id"""
    id_data = soup.find("section", id="listing-detail")
    id = id_data.get("data-listing-id") if id_data else random.randint(10000000, 99999999)

    return id


def get_offer_title(soup: BeautifulSoup):
    """get offer title"""
    title = soup.find("section", id="top-data")

    if not title:
        title = ""

    mr = title.find("h1").find("b")
    title_text = mr.next_sibling.strip()
    title = f"{mr.text} {title_text}"

    return title


def get_offer_price(soup: BeautifulSoup):
    """get offer price"""
    price = soup.find("div", id="price-location").find("div", class_="card-body").find("div").find("div").next_sibling
    price = price.text.strip().split("\xa0")[0].replace(".", "") if price else 0

    return price


def get_offer_description(soup: BeautifulSoup):
    """get offer description"""

    description = ""

    description_data = soup.find("div", id="description").find("div", class_="card-body")

    if description_data:
        data = description_data.text.strip()

        # Remove non-breaking spaces, newlines, and extra spaces
        description = re.sub(r"[\xa0\n\s]+", " ", data).strip()

    return description


def get_offer_phone(url: str, id: str):
    """using selenium to get offer phone"""

    phone_number = ""

    driver = webdriver.Firefox()
    driver.get(url)

    try:
        modal_trigger = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, f"button.btn.btn-primary[data-inquiry-btn='{id}']"))
        )
        driver.execute_script("arguments[0].click();", modal_trigger)

        # Wait for the modal to appear
        modal = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.modal-body")))

        # Find the phone number element within the modal
        phone_number_element = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li a[href^='tel:']"))
        )

        href_value = phone_number_element.get_attribute("href")
        phone_number = href_value.replace("tel:", "").strip()

    finally:
        driver.quit()

    return phone_number


def get_offer_properties(soup: BeautifulSoup) -> tuple[int, int, str]:
    """get offer properties"""
    mileage = 0
    power = 0
    color = ""

    properties = soup.find("div", id="properties").find("div", class_="card-body").find_all("dl")

    if not properties:
        return mileage, power, color

    for property in properties:
        name = property.find("dt").text.strip().replace(":", "")
        value = property.find("dd").text.strip().replace(":", "")

        if name == "Farbe":
            color = value
        elif name == "Kilometerstand":
            data = re.search(r"\d+", value)
            mileage = int(data.group()) if data else 0
        elif name == "Leistung":
            data = re.search(r"(\d+)\s*kW", value)
            power = int(data.group(1)) if data else 0

    return mileage, power, color


def get_offer_details(data: str, url: str):
    """
    Get offer details without phone number

    :param url: offer page url

    :return: offer details
    """

    soup = BeautifulSoup(data, "html.parser")

    id = get_offer_id(soup)
    title = get_offer_title(soup)
    price = get_offer_price(soup)
    description = get_offer_description(soup)
    mileage, power, color = get_offer_properties(soup)

    vehicle = Vehicle(
        id=id,
        href=url,
        title=title,
        price=price,
        mileage=mileage,
        power=power,
        color=color,
        description=description,
    )

    return vehicle


async def fetch_offers(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.text()

            return get_random_offer_detail_url(data)


async def fetch_offer_details(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.text()

            return get_offer_details(data, url)


async def fetch_offer_images_urls(url: str, id: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.text()

            return get_offer_images(data, id)


async def fetch_offer_image(url: str, id: str, index: int):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.read()

            write_image_to_file(data, id, index)


async def fetch_pages_urls(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.text()

            soup = BeautifulSoup(data, "html.parser")

            pages = soup.find("ul", class_="pagination").find_all("li", class_="page-item")

            if not pages:
                return []

            return [BASE_URL + page.find("a").get("href") for page in pages][1:-1]


def write_data_to_file(data):
    if not os.path.exists("data"):
        os.makedirs("data")

    with open("data/data.json", "a") as json_file:
        json.dump(data.model_dump(), json_file, indent=2)


def write_image_to_file(data: str, id: str, index: int):
    base_dir = "data"

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    id_dir = os.path.join(base_dir, str(id))

    if not os.path.exists(id_dir):
        os.makedirs(id_dir)

    file_path = os.path.join(id_dir, f"image-{id}-{index}.jpg")

    with open(file_path, "wb") as image_file:
        image_file.write(data)


async def get_gather_data(url: str):
    pages_urls = await asyncio.gather(asyncio.create_task(fetch_pages_urls(url)))

    tasks = []

    for url in pages_urls[0]:
        task = asyncio.create_task(fetch_offers(url))
        tasks.append(task)

    offer_urls = await asyncio.gather(*tasks)
    print(offer_urls)

    tasks = []

    for url in offer_urls:
        task = asyncio.create_task(fetch_offer_details(url))
        tasks.append(task)

    ads = await asyncio.gather(*tasks)

    tasks = []

    for offer in ads:
        task = asyncio.create_task(fetch_offer_images_urls(offer.href, offer.id))
        tasks.append(task)

    offer_images = await asyncio.gather(*tasks)

    tasks = []

    for image_url in offer_images:
        for id, index, url in image_url:
            task = asyncio.create_task(fetch_offer_image(url, id, index))
            tasks.append(task)

    await asyncio.gather(*tasks)

    return ads


def main():
    # asyncronous function to get offers without phone number because for fetching phone number need to use sync selenium
    offers_without_phone = asyncio.run(
        get_gather_data("https://www.truckscout24.de/transporter/gebraucht/kuehl-iso-frischdienst/renault")
    )

    for offer in offers_without_phone:
        offer.phone = get_offer_phone(offer.href, offer.id)

    ad_list = AdList(ads=offers_without_phone)

    write_data_to_file(ad_list)


if __name__ == "__main__":
    start_time = time.time()

    main()

    time_difference = time.time() - start_time
    print(f"Scraping time: %.2f seconds." % time_difference)
