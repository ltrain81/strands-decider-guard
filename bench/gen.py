"""Seeded generators for synthetic values (names, numbers, addresses). Values are created at runtime only."""
import random

SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
GIVEN = list("민서지현준우예도하윤수연영진호성은태재희")
ROMAN = ["min", "seo", "ji", "hyun", "jun", "woo", "ye", "do", "ha", "yoon", "su", "yeon", "young", "jin", "ho",
         "sung", "eun", "tae", "jae", "hee"]
EN_FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Ethan", "Mia", "Lucas", "Chloe", "Mason", "Grace", "Owen"]
EN_LAST = ["Harper", "Bennett", "Calloway", "Delgado", "Whitfield", "Okafor", "Lindqvist", "Moreau", "Castellanos"]
MAIL_HOSTS = [("na", "ver"), ("da", "um"), ("g", "mail"), ("ka", "kao"), ("han", "mail"), ("out", "look")]
TLDS = [".com", ".net", ".co.kr"]
CITIES = ["서울특별시 강남구", "서울특별시 마포구", "부산광역시 해운대구", "인천광역시 연수구", "경기도 성남시 분당구",
          "대구광역시 수성구", "대전광역시 유성구", "광주광역시 서구", "경기도 수원시 영통구", "울산광역시 남구"]
ROADS = ["테헤란로", "월드컵북로", "센텀중앙로", "판교역로", "달구벌대로", "대학로", "중앙대로", "봉은사로"]
BANKS = ["국민은행", "신한은행", "우리은행", "하나은행", "농협은행", "카카오뱅크", "기업은행"]
DEPTS = ["영업2팀", "재무팀", "개발1팀", "인사팀", "마케팅팀", "고객지원팀", "물류팀"]
TITLES = ["대리", "과장", "차장", "사원", "팀장", "책임", "선임"]


class Gen:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def digits(self, n):
        return "".join(str(self.r.randint(0, 9)) for _ in range(n))

    def ko_name(self):
        return self.r.choice(SURNAMES) + "".join(self.r.sample(GIVEN, 2))

    def en_name(self):
        return f"{self.r.choice(EN_FIRST)} {self.r.choice(EN_LAST)}"

    def rrn(self):
        """Resident registration number with a valid check digit."""
        yy, mm, dd = self.r.randint(60, 99), self.r.randint(1, 12), self.r.randint(1, 28)
        body = f"{yy:02d}{mm:02d}{dd:02d}" + str(self.r.choice([1, 2])) + self.digits(5)
        w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
        check = (11 - sum(int(c) * k for c, k in zip(body, w)) % 11) % 10
        full = body + str(check)
        return full[:6] + "-" + full[6:]

    def mobile(self):
        return f"010-{self.r.randint(2000, 9999)}-{self.digits(4)}"

    def email(self):
        user = "".join(self.r.sample(ROMAN, 2)) + self.r.choice(["", ".", "_"]) + self.digits(self.r.choice([0, 2, 4]))
        host = "".join(self.r.choice(MAIL_HOSTS))
        return user.strip("._") + "@" + host + self.r.choice(TLDS)

    def en_email(self, name):
        first, last = name.lower().split()
        host = "".join(self.r.choice(MAIL_HOSTS))
        return f"{first}.{last}{self.digits(2)}@{host}.com"

    def address(self):
        return (f"{self.r.choice(CITIES)} {self.r.choice(ROADS)} {self.r.randint(1, 400)}, "
                f"{self.r.randint(101, 115)}동 {self.r.randint(1, 25)}{self.r.randint(1, 4):02d}호")

    def card(self):
        """16-digit number with a valid Luhn check digit, grouped by 4."""
        body = [int(c) for c in self.r.choice(["4", "5", "9"]) + self.digits(14)]
        s = 0
        for i, d in enumerate(reversed(body)):
            if i % 2 == 0:
                d *= 2
                d = d - 9 if d > 9 else d
            s += d
        num = "".join(map(str, body)) + str((10 - s % 10) % 10)
        return "-".join(num[i:i + 4] for i in range(0, 16, 4))

    def account(self):
        fmt = self.r.choice([(3, 2, 6), (3, 3, 6), (4, 2, 7), (6, 2, 6), (3, 6, 5)])
        return self.r.choice(BANKS), "-".join(self.digits(n) for n in fmt)

    def passport(self):
        return self.r.choice("MSR") + self.digits(8)

    def won(self, lo, hi, step=10):
        return f"{self.r.randrange(lo, hi, step):,}"

    def pick(self, xs):
        return self.r.choice(xs)
