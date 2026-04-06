import requests
import random

API_URL = "http://localhost:8000/api/products/"
TOTAL = 10000
BATCH_SIZE = 500

# Latvian words with garumzīmes
adjectives = [
    "Ātrais", "Lētais", "Dārgais", "Ērtais", "Jaudīgais",
    "Stilīgais", "Spēcīgais", "Kompaktais", "Viegls", "Klusais",
    "Drošais", "Svaigais", "Mūsdienīgais", "Izturīgais"
]

nouns = [
    "krēsls", "galds", "lampa", "tējkanna", "mikrofons",
    "skaļrunis", "pele", "tastatūra", "pulkstenis", "kamera",
    "printeris", "mugursoma", "putekļsūcējs", "ventilators"
]

features = [
    "ērts", "jaudīgs", "izturīgs", "kompakts", "ūdensizturīgs",
    "stilīgs", "ātrs", "kluss", "drošs", "viegls"
]

categories = [f"Kategorija {i}" for i in range(1, 21)]
brands = [f"Zīmols {i}" for i in range(1, 51)]

used_names = set()


def normalize_text(text):
    return text.lower()


def random_name():
    # ensures uniqueness
    while True:
        name = f"{random.choice(adjectives)} {random.choice(nouns)} {random.randint(100,9999)}"
        if name not in used_names:
            used_names.add(name)
            return name


def random_description():
    text = (
        f"{random.choice(features)} un {random.choice(features)} produkts "
        f"ikdienai ar {random.choice(features)} dizainu."
    )
    return text[:100]  # cap at 100 chars


def generate_product(i):
    name = random_name()
    desc = random_description()

    return {
        "company": random.choice(brands),
        "category": random.choice(categories),
        "name": name,
        "name_normalized": normalize_text(name),
        "description": desc,
        "description_normalized": normalize_text(desc),
        "price": round(random.uniform(1, 2000), 2),
        "available": i % 2 == 0,
        "rating": round(random.uniform(1, 10), 2),
    }


def main():
    batch = []
    created_total = 0

    for i in range(TOTAL):
        batch.append(generate_product(i))

        if len(batch) >= BATCH_SIZE:
            res = requests.post(API_URL, json=batch)
            if res.status_code != 201:
                print("Error:", res.text)
                return

            created_total += res.json().get("created", len(batch))
            print(f"{created_total}/{TOTAL}")
            batch = []

    if batch:
        res = requests.post(API_URL, json=batch)
        if res.status_code != 201:
            print("Error:", res.text)
            return
        created_total += res.json().get("created", len(batch))

    print("Done:", created_total)


if __name__ == "__main__":
    main()