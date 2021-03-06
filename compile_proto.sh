# Compile Protobuff interface
GSERVER_DIR="opt/scopeserver/dataserver/modules/gserver"
python -m grpc.tools.protoc  --python_out=${GSERVER_DIR} --grpc_python_out=${GSERVER_DIR} --proto_path=src/proto/ s.proto
A="import s_pb2 as s__pb2"
B="from scopeserver.dataserver.modules.gserver import s_pb2 as s__pb2"
# Update the import
sed -i -e "s#$A#$B#g" "$GSERVER_DIR/s_pb2_grpc.py"
