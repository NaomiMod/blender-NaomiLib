clearListener()

fname = getOpenFileName \ 
caption:"Naomi Model" \
types:"NL Model (*.bin)|*.bin" \
historyCategory:"3D Model"
f = fopen fname "rb"


fn ReadFixedString bstream fixedLen = (
   local str =""
   for i=1 to fixedLen do (
      str+=bit.intAsChar (ReadByte bstream #unsigned)
   )
   str
)

fn readMeshSmall f =
(
	Vertices = #()
	Normals = #()
	TexCoords = #()
	Faces = #()
	
	Unused = readlong f
	vertexNum = readlong f
	
	print vertexnum
	
	for i = 1 to vertexNum do
	(
		x = readfloat f
		y = readfloat f
		z = readfloat f
		
		vertex = point3 x y z
		Vertices[i] = vertex
        print vertex
		
		nx = readfloat f
		ny = readfloat f
		nz = readfloat f
		
		normal = point3 nx ny nz
		
		Normals[i] = normal
        
		print normal
		
		u = readfloat f
		v = 1 - readfloat f
		
		texcoord = point3 u v 0
		TexCoords[i] = texcoord
		
		print texcoord
		
		
	)
	


	for i = 1 to (vertexNum - 2) by 1 do
		(
			x = i
			if(mod i 2 == 1) then
				(
				y = i + 1
				z = i + 2
			)
			else
			(
				y = i + 2
				z = i + 1
			)				
			face = point3 x y z
			append Faces face
		)

	msh = mesh vertices:Vertices faces:Faces tverts:TexCoords
		
	mmesh = msh.mesh
	buildTVFaces mmesh
	for i = 1 to mmesh.numfaces do
	(
		setTVFace mmesh i (getFace mmesh i)
	)
)

fn readBlock f numChunks offset =
(
	fseek f offset #seek_set
	
	for i = 1 to numChunks do
	(
			readMeshSmall f
	)
	
)

readBlock f 05 0x68
print "------------"


fclose f