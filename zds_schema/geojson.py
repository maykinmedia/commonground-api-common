from collections import OrderedDict

from drf_yasg import openapi
from drf_yasg.inspectors import FieldInspector, NotHandled
from rest_framework_gis.fields import GeometryField

REF_NAME_GEOJSON_GEOMETRY = 'GeoJSONGeometry'


def register_geojson(definitions):
    Geometry = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        title="Geometry",
        description="GeoJSON geometry",
        discriminator='type',
        required='type',
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1'),
        properties=OrderedDict((
            ('type', openapi.Schema(
                type=openapi.TYPE_STRING,
                enum=[
                    'Point',
                    'MultiPoint',
                    'LineString',
                    'MultiLineString',
                    'Polygon',
                    'MultiPolygon',
                    'Feature',
                    'FeatureCollection',
                    'GeometryCollection',
                ],
                description="The geometry type"
            )),
        ))
    )
    definitions.set('Geometry', Geometry)

    Point2D = openapi.Schema(
        type=openapi.TYPE_ARRAY,
        title="Point2D",
        description="A 2D point",
        items=openapi.Schema(type=openapi.TYPE_NUMBER),
        maxItems=2,
        minItems=2
    )
    definitions.set('Point2D', Point2D)

    Point = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="GeoJSON point geometry",
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1.2'),
        allOf=[
            openapi.SchemaRef(definitions, 'Geometry'),
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('coordinates', openapi.SchemaRef(definitions, 'Point2D')),
                ))
            )
        ]
    )
    definitions.set('Point', Point)

    MultiPoint = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="GeoJSON multi-point geometry",
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1.3'),
        allOf=[
            openapi.SchemaRef(definitions, 'Geometry'),
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('coordinates', openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.SchemaRef(definitions, 'Point2D'),
                    )),
                ))
            )
        ]
    )
    definitions.set('MultiPoint', MultiPoint)

    LineString = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="GeoJSON line-string geometry",
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1.4'),
        allOf=[
            openapi.SchemaRef(definitions, 'Geometry'),
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('coordinates', openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.SchemaRef(definitions, 'Point2D'),
                        minItems=2,
                    )),
                ))
            )
        ]
    )
    definitions.set('LineString', LineString)

    MultiLineString = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="GeoJSON multi-line-string geometry",
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1.5'),
        allOf=[
            openapi.SchemaRef(definitions, 'Geometry'),
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('coordinates', openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.SchemaRef(definitions, 'Point2D')
                        )
                    )),
                ))
            )
        ]
    )
    definitions.set('MultiLineString', MultiLineString)

    Polygon = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="GeoJSON polygon geometry",
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1.6'),
        allOf=[
            openapi.SchemaRef(definitions, 'Geometry'),
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('coordinates', openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.SchemaRef(definitions, 'Point2D')
                        )
                    )),
                ))
            )
        ]
    )
    definitions.set('Polygon', Polygon)

    MultiPolygon = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="GeoJSON multi-polygon geometry",
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1.7'),
        allOf=[
            openapi.SchemaRef(definitions, 'Geometry'),
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('coordinates', openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.Schema(
                                type=openapi.TYPE_ARRAY,
                                items=openapi.SchemaRef(definitions, 'Point2D')
                            )
                        )
                    )),
                ))
            )
        ]
    )
    definitions.set('MultiPolygon', MultiPolygon)

    GeometryCollection = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        description="GeoJSON multi-polygon geometry",
        externalDocs=OrderedDict(url='https://tools.ietf.org/html/rfc7946#section-3.1.8'),
        allOf=[
            openapi.SchemaRef(definitions, 'Geometry'),
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('geometries', openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.SchemaRef(definitions, 'Geometry')
                    )),
                ))
            )
        ]
    )
    definitions.set('GeometryCollection', GeometryCollection)

    GeoJSONGeometry = openapi.Schema(
        title=REF_NAME_GEOJSON_GEOMETRY,
        type=openapi.TYPE_OBJECT,
        oneOf=[
            openapi.SchemaRef(definitions, 'Point'),
            openapi.SchemaRef(definitions, 'MultiPoint'),
            openapi.SchemaRef(definitions, 'LineString'),
            openapi.SchemaRef(definitions, 'MultiLineString'),
            openapi.SchemaRef(definitions, 'Polygon'),
            openapi.SchemaRef(definitions, 'MultiPolygon'),
            openapi.SchemaRef(definitions, 'GeometryCollection'),
        ]
    )
    definitions.set(REF_NAME_GEOJSON_GEOMETRY, GeoJSONGeometry)


class GeometryFieldInspector(FieldInspector):

    def field_to_swagger_object(self, field, swagger_object_type, use_references, **kwargs):
        if not isinstance(field, GeometryField):
            return NotHandled

        definitions = self.components.with_scope(openapi.SCHEMA_DEFINITIONS)

        if not definitions.has('Geometry'):
            register_geojson(definitions)

        return openapi.SchemaRef(definitions, REF_NAME_GEOJSON_GEOMETRY)