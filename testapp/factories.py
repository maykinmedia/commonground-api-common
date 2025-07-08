import factory


class GroupFactory(factory.django.DjangoModelFactory):
    name = factory.Faker("bs")

    class Meta:
        model = "testapp.Group"


class PersonFactory(factory.django.DjangoModelFactory):
    name = factory.Faker("name")
    address_street = factory.Faker("street_name")
    address_number = factory.Faker("building_number")

    class Meta:
        model = "testapp.Person"


class HobbyFactory(factory.django.DjangoModelFactory):
    name = factory.Faker("bs")

    class Meta:
        model = "testapp.Hobby"


class NotitieFactory(factory.django.DjangoModelFactory):
    onderwerp = factory.Faker("sentence")
    tekst = factory.Faker("paragraph")
    aangemaakt_door = factory.Faker("name")

    class Meta:
        model = "testapp.Notitie"
