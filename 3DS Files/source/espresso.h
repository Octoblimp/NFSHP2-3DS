// espresso -- the seams for the Espresso editor's live link.
//
// Espresso is bWare's level editor, and "Caffeine" its object database: a
// development build pushes objects into the running editor so a designer
// can see them in place. The client half ships in the image at
// 0x00243110..0x002437e8 and talks to the editor over the debug channel,
// which a retail disc never opens. The port has no editor, so every call
// the game makes into that client is a function pointer here: NULL is a
// call the port cannot make, and reaching it aborts.
//
//   espCreateObject(const char *, const char *)   0x00243110
//   espDeleteObject(unsigned int)                 0x002431c0
//   espSetObjectPosition(unsigned int, FloatVector *)
//                                                 0x00243308
//   espCreateUserMesh(unsigned int, int)          0x00243760
//   espSetUserMeshFace(unsigned int, int, FloatVector *)
//                                                 0x002437e8
//
// Every object handle the game keeps (Car, VCPolyhedron, VCWitness and the
// collision bodies all have a pCaffeineObj) is only ever set by a create
// call, and every create call is behind a debug switch that is zero on the
// disc -- so the seams are here for completeness, and nothing reaches them.
//
// espSetObjectPosition's seam is the one car.h declares as
// gEspSetObjectPositionFn (Car was its first caller); the declaration below
// is the same type, and espresso.c holds the definition.

#ifndef ESPRESSO_H
#define ESPRESSO_H

#include <stdint.h>

#include "bvector.h"

// FloatVector (type#288): three floats and nothing else, twelve bytes, where
// a bVector3 is sixteen. A user mesh face is passed as four of them.
typedef struct FloatVector {
    float x, y, z;
} FloatVector;

typedef void *(*EspCreateObjectFn)(const char *layer, const char *type);
typedef void  (*EspDeleteObjectFn)(void *obj);
typedef void  (*EspCreateUserMeshFn)(void *obj, int32_t faces);
typedef void  (*EspSetUserMeshFaceFn)(void *obj, int32_t face,
                                      FloatVector *verts);

extern EspCreateObjectFn    gEspCreateObjectFn;
extern EspDeleteObjectFn    gEspDeleteObjectFn;
extern EspCreateUserMeshFn  gEspCreateUserMeshFn;
extern EspSetUserMeshFaceFn gEspSetUserMeshFaceFn;
extern void (*gEspSetObjectPositionFn)(void *obj, bVector3 *pos);

// The calls, each aborting if its seam is unset.
void *esp_create_object(const char *layer, const char *type);
void  esp_delete_object(void *obj);
void  esp_create_user_mesh(void *obj, int32_t faces);
void  esp_set_user_mesh_face(void *obj, int32_t face, FloatVector *verts);
void  esp_set_object_position(void *obj, bVector3 *pos);

#endif
