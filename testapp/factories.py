from factory.django import DjangoModelFactory
from factory.faker import Faker


class GroupFactory(DjangoModelFactory):
    name = Faker("bs")

    class Meta:  # pyright: ignore
        model = "testapp.Group"


class PersonFactory(DjangoModelFactory):
    name = Faker("name")
    address_street = Faker("street_name")
    address_number = Faker("building_number")

    class Meta:  # pyright: ignore
        model = "testapp.Person"


class HobbyFactory(DjangoModelFactory):
    name = Faker("bs")

    class Meta:  # pyright: ignore
        model = "testapp.Hobby"


class NotitieFactory(DjangoModelFactory):
    onderwerp = Faker("sentence")
    tekst = Faker("paragraph")
    aangemaakt_door = Faker("name")

    class Meta:  # pyright: ignore
        model = "testapp.Notitie"
