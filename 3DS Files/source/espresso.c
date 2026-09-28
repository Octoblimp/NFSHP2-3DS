// espresso -- see espresso.h.

#include "espresso.h"

#include <stdio.h>
#include <stdlib.h>

EspCreateObjectFn    gEspCreateObjectFn;
EspDeleteObjectFn    gEspDeleteObjectFn;
EspCreateUserMeshFn  gEspCreateUserMeshFn;
EspSetUserMeshFaceFn gEspSetUserMeshFaceFn;
EspSetAttributeIntFn gEspSetAttributeIntFn;
void (*gEspSetObjectPositionFn)(void *obj, bVector3 *pos);

static void unported(const char *what)
{
    fprintf(stderr, "espresso: %s is not ported\n", what);
    abort();
}

void *esp_create_object(const char *layer, const char *type)
{
    if (gEspCreateObjectFn == NULL)
        unported("espCreateObject");
    return gEspCreateObjectFn(layer, type);
}

void esp_delete_object(void *obj)
{
    if (gEspDeleteObjectFn == NULL)
        unported("espDeleteObject");
    gEspDeleteObjectFn(obj);
}

void esp_create_user_mesh(void *obj, int32_t faces)
{
    if (gEspCreateUserMeshFn == NULL)
        unported("espCreateUserMesh");
    gEspCreateUserMeshFn(obj, faces);
}

void esp_set_user_mesh_face(void *obj, int32_t face, FloatVector *verts)
{
    if (gEspSetUserMeshFaceFn == NULL)
        unported("espSetUserMeshFace");
    gEspSetUserMeshFaceFn(obj, face, verts);
}

void esp_set_object_position(void *obj, bVector3 *pos)
{
    if (gEspSetObjectPositionFn == NULL)
        unported("espSetObjectPosition");
    gEspSetObjectPositionFn(obj, pos);
}

void esp_set_attribute_int(uint32_t obj, const char *name, int32_t value)
{
    if (gEspSetAttributeIntFn != NULL)
        gEspSetAttributeIntFn(obj, name, value);
}
